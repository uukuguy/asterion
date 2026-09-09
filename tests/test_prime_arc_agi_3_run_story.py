"""Bounded trust and correctness tests for ARC-AGI-3 run-story artifacts."""

from __future__ import annotations

import json
import io
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.prime.p7.broker import digest
from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
from asterion import cli as asterion_cli
from asterion.applications.prime.p7.run_story import (
    RunStoryError,
    ArtifactApplication,
    analyze_bundle,
    compile_run,
    read_run_evidence,
    render_web,
)
from asterion.applications.prime.p7.run_story.operator_narrator import (
    PiRunStoryNarrator,
)


class _StubNarrator:
    model_id = "stub-model"

    def __init__(self, story: dict[str, object]) -> None:
        self.story = story

    def generate(self, request: object) -> dict[str, object]:
        del request
        return self.story


def _valid_story() -> dict[str, object]:
    return {
        "schema": "asterion.prime.arc-agi-3-run-story-narration/v1",
        "kind": "narrated",
        "title": "一次受控移动验证",
        "summary": "动作改变了中心对象，并在第一步完成关卡。",
        "episodes": [
            {
                "step_start": 1,
                "step_end": 1,
                "title": "验证移动",
                "observation": "初始画面存在一个可变单元。",
                "hypothesis": "ACTION1 可能移动受控对象。",
                "experiment": "执行 ACTION1 并比较前后画面。",
                "result": "画面发生变化，环境报告完成。",
                "model_update": "该动作与完成条件存在直接关系。",
                "consequence": "无需继续尝试其他动作。",
                "citations": {"actions": [1], "frames": [0, 1]},
                "confidence": "fact",
                "decisive": True,
            }
        ],
        "understanding": {
            "controlled_object": {
                "resolved": False,
                "answer": "证据不足",
                "confidence": "tentative",
                "citations": {"actions": [1], "frames": [0, 1]},
            },
            "movement_behavior": {
                "resolved": True,
                "answer": "ACTION1 会改变画面中的受控状态。",
                "confidence": "fact",
                "citations": {"actions": [1], "frames": [0, 1]},
            },
            "visual_relationship": {
                "resolved": False,
                "answer": "证据不足",
                "confidence": "tentative",
                "citations": {"actions": [1], "frames": [0, 1]},
            },
            "completion_condition": {
                "resolved": True,
                "answer": "执行 ACTION1 后环境进入完成状态。",
                "confidence": "fact",
                "citations": {"actions": [1], "frames": [0, 1]},
            },
        },
    }


def _grid(changed: bool = False) -> list[list[int]]:
    grid = [[4 for _column in range(64)] for _row in range(64)]
    grid[20][20] = 1 if changed else 0
    return grid


def _observation_digest_frames(
    grids: list[list[list[int]]], levels_completed: int
) -> str:
    return digest(
        {
            "available_actions": ("ACTION1", "ACTION2", "ACTION3", "ACTION4"),
            "frame": tuple(tuple(tuple(row) for row in grid) for grid in grids),
            "levels_completed": levels_completed,
            "state": "FINISHED" if levels_completed else "NOT_FINISHED",
            "win_levels": 7,
        }
    )


def _observation_digest(grid: list[list[int]], levels_completed: int) -> str:
    return _observation_digest_frames([grid], levels_completed)


def _recording_row(
    *,
    action: str,
    grid: list[list[int]],
    levels_completed: int,
    timestamp: str,
    animation: list[list[list[int]]] | None = None,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "data": {
            "game_id": "fixture-game",
            "state": "FINISHED" if levels_completed else "NOT_FINISHED",
            "levels_completed": levels_completed,
            "win_levels": 7,
            "action_input": {"id": action, "data": {}, "reasoning": None},
            "guid": "fixture-guid",
            "full_reset": action == "RESET",
            "available_actions": [1, 2, 3, 4],
            "frame": [grid] if animation is None else animation,
        },
    }


def write_completed_fixture(
    root: Path, *, worker_secret: str = "private", animated: bool = False
) -> Path:
    run_root = root / "fixture-run"
    trace_root = run_root / "trace"
    recording_root = run_root / "recordings" / "fixture-recording"
    trace_root.mkdir(parents=True)
    recording_root.mkdir(parents=True)
    before = _grid()
    after = _grid(changed=True)
    middle = _grid()
    middle[20][19] = 1
    middle[20][20] = 1
    animation = [middle, after] if animated else [after]
    before_sha = _observation_digest(before, 0)
    after_sha = _observation_digest_frames(animation, 1)
    recorder = PrimeTraceRecorder(trace_root)
    recorder.append(
        "arc.action",
        P7_TRACE_IDENTITIES,
        {
            "action": "ACTION1",
            "after_sha256": after_sha,
            "before_sha256": before_sha,
            "levels_completed": 1,
            "sequence": 1,
        },
    )
    recorder.append(
        "arc.usage.reported",
        P7_TRACE_IDENTITIES,
        {"input_tokens": 120, "output_tokens": 31},
    )
    recorder.append(
        "arc.run.completed",
        P7_TRACE_IDENTITIES,
        {
            "levels_completed": 1,
            "primitive_actions": 1,
            "replay_sha256": "sha256:" + "a" * 64,
            "terminal_reason": "level-completed",
        },
    )
    recorder.seal()
    rows = (
        _recording_row(
            action="RESET",
            grid=before,
            levels_completed=0,
            timestamp="2026-09-09T00:00:00+00:00",
        ),
        _recording_row(
            action="RESET",
            grid=before,
            levels_completed=0,
            timestamp="2026-09-09T00:00:00.001000+00:00",
        ),
        _recording_row(
            action="ACTION1",
            grid=after,
            levels_completed=1,
            timestamp="2026-09-09T00:00:01+00:00",
            animation=animation,
        ),
    )
    recording = recording_root / "fixture-game-guid.jsonl"
    recording.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    (run_root / "worker-cells.jsonl").write_text(
        json.dumps(
            {
                "cell_count": 1,
                "code": worker_secret,
                "code_sha256": "b" * 64,
                "is_error": False,
                "output": worker_secret,
                "output_sha256": "c" * 64,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema": "asterion.prime.p7-live-private-summary/v1",
        "run_id": "fixture-run",
        "receipt": {
            "completed_level_count": 1,
            "partial_game_score": "3.571429",
            "primitive_action_count": 1,
            "promotion": "unpromoted",
            "receipt_sha256": "d" * 64,
            "scope": "p7-solving",
        },
        "broker": {
            "levels_completed": 1,
            "primitive_actions": 1,
            "replay_sha256": "sha256:" + "a" * 64,
            "terminal_reason": "level-completed",
        },
        "replay_verified": True,
        "sealed_trace": True,
        "cleanup_complete": True,
        "comparison_report": None,
        "reason": None,
        "failure": None,
        "diagnostics": {"worker_cell_count": 1},
    }
    (run_root / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return run_root.resolve()


class TestPrimeArcAgi3RunStory(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_reads_completed_evidence_without_copying_private_content(self) -> None:
        evidence = read_run_evidence(
            write_completed_fixture(self.root, worker_secret="RAW-WORKER-SENTINEL")
        )

        self.assertEqual(evidence.game_id, "fixture-game")
        self.assertEqual(evidence.run_id, "fixture-run")
        self.assertEqual(tuple(action.name for action in evidence.actions), ("ACTION1",))
        self.assertEqual(evidence.worker_cell_count, 1)
        self.assertEqual(
            evidence.usage, {"input_tokens": 120, "output_tokens": 31}
        )
        self.assertEqual(evidence.verification, "VERIFIED")
        self.assertNotIn("RAW-WORKER-SENTINEL", repr(evidence))

    def test_rejects_ambiguous_recording(self) -> None:
        run_root = write_completed_fixture(self.root)
        duplicate = run_root / "recordings" / "other" / "duplicate.jsonl"
        duplicate.parent.mkdir()
        duplicate.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)

    def test_compiles_deterministic_process_bundle_without_worker_text(self) -> None:
        run_root = write_completed_fixture(
            self.root, worker_secret="RAW-WORKER-SENTINEL"
        )
        artifact_root = self.root / "artifacts" / "arc-agi-3"

        first = compile_run(run_root, artifact_root)
        second = compile_run(run_root, artifact_root)

        self.assertEqual(first.bundle_sha256, second.bundle_sha256)
        run = json.loads((first.run_root / "data" / "run.json").read_text())
        self.assertEqual(run["action_count"], 1)
        self.assertEqual(
            run["usage"], {"input_tokens": 120, "output_tokens": 31}
        )
        self.assertIsNone(run["elapsed_seconds"])
        self.assertEqual(
            len((first.run_root / "data" / "frames.jsonl").read_text().splitlines()),
            2,
        )
        published = b"".join(
            path.read_bytes() for path in first.run_root.rglob("*") if path.is_file()
        )
        self.assertNotIn(b"RAW-WORKER-SENTINEL", published)
        catalog = json.loads((artifact_root / "catalog.json").read_text())
        self.assertEqual(catalog["runs"][0]["run_id"], "fixture-run")

    def test_compiler_keeps_animation_frames_inside_one_action(self) -> None:
        bundle = compile_run(
            write_completed_fixture(self.root, animated=True),
            self.root / "artifacts" / "arc-agi-3",
        )

        actions = [
            json.loads(line)
            for line in (bundle.run_root / "data" / "actions.jsonl")
            .read_text()
            .splitlines()
        ]
        diffs = [
            json.loads(line)
            for line in (bundle.run_root / "data" / "diffs.jsonl")
            .read_text()
            .splitlines()
        ]
        self.assertEqual((actions[0]["before_frame"], actions[0]["after_frame"]), (0, 2))
        self.assertEqual(actions[0]["changed_cell_count"], 1)
        self.assertEqual([diff["action_index"] for diff in diffs], [1, 1])

    def test_analysis_is_versioned_and_rejects_fact_mutation(self) -> None:
        bundle = compile_run(
            write_completed_fixture(self.root),
            self.root / "artifacts" / "arc-agi-3",
        )

        accepted = analyze_bundle(bundle.run_root, _StubNarrator(_valid_story()))
        invalid: dict[str, Any] = _valid_story()
        invalid["action_count"] = 999
        rejected = analyze_bundle(bundle.run_root, _StubNarrator(invalid))

        self.assertEqual(accepted.status, "accepted")
        self.assertEqual(accepted.story["episodes"][0]["citations"]["actions"], [1])
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.story["kind"], "factual-fallback")
        self.assertNotEqual(accepted.analysis_id, rejected.analysis_id)

    def test_pi_narrator_accepts_one_json_response_without_exposing_config(self) -> None:
        calls: list[str] = []
        narrator = PiRunStoryNarrator(
            model_id="fixture-model",
            invoke=lambda prompt: calls.append(prompt) or json.dumps(_valid_story()),
        )
        request = type(
            "Request",
            (),
            {
                "schema": "asterion.prime.arc-agi-3-run-story-narration/v1",
                "run": {"run_id": "fixture-run"},
                "actions": ({"action_index": 1},),
                "frames": ({"frame_index": 0, "grid": [[0]]},),
                "diffs": ({"action_index": 1},),
                "reasoning_evidence": ({"cell_index": 1},),
            },
        )()

        story = narrator.generate(request)

        self.assertEqual(story["kind"], "narrated")
        self.assertEqual(len(calls), 1)
        self.assertIn('"frames"', calls[0])
        self.assertNotIn("fixture-model", repr(narrator))

    def test_render_is_deterministic_and_bound_to_data(self) -> None:
        bundle = compile_run(
            write_completed_fixture(self.root),
            self.root / "artifacts" / "arc-agi-3",
        )
        analysis = analyze_bundle(bundle.run_root, _StubNarrator(_valid_story()))

        first = render_web(bundle.run_root, analysis.analysis_id)
        second = render_web(bundle.run_root, analysis.analysis_id)
        changed = render_web(
            bundle.run_root, analysis.analysis_id, theme_version="poster-v2"
        )

        self.assertEqual(first.render_id, second.render_id)
        self.assertNotEqual(first.render_id, changed.render_id)
        self.assertEqual(
            first.manifest["bundle_sha256"], changed.manifest["bundle_sha256"]
        )
        html = (first.render_root / "index.html").read_text(encoding="utf-8")
        self.assertIn("ARC-AGI-3", html)
        self.assertIn("关卡目标、对象含义和动力学规则不会直接给出", html)
        self.assertIn("解题事实、事后分析与网页渲染分别版本化", html)
        self.assertIn("ONLINE EXPERIMENTS", html)
        self.assertIn("CONTROLLED EXECUTION", html)
        self.assertNotIn("3.571429", html)

    def test_server_is_read_only_utf8_and_rejects_escape(self) -> None:
        artifact_root = self.root / "artifacts" / "arc-agi-3"
        bundle = compile_run(write_completed_fixture(self.root), artifact_root)
        analysis = analyze_bundle(bundle.run_root, _StubNarrator(_valid_story()))
        render_web(bundle.run_root, analysis.analysis_id)
        app = ArtifactApplication(artifact_root)

        root = app.handle("GET", "/")

        self.assertEqual(root.status, 200)
        self.assertIn("text/html; charset=utf-8", root.headers["Content-Type"])
        self.assertNotIn(b"<style>", root.body)
        self.assertEqual(app.handle("GET", "/_catalog.css").status, 200)
        self.assertEqual(app.handle("POST", "/").status, 405)
        self.assertEqual(app.handle("GET", "/../.env").status, 404)
        self.assertEqual(app.handle("GET", "/%2e%2e/.env").status, 404)
        self.assertEqual(
            app.handle("GET", "/missing").body, b'{"error":"not-found"}\n'
        )

    def test_cli_routes_compile_without_provider_discovery(self) -> None:
        run_root = write_completed_fixture(self.root)
        stdout, stderr = io.StringIO(), io.StringIO()
        previous = Path.cwd()
        os.chdir(self.root)
        try:
            code = asterion_cli.main(
                ["arc-story", "compile", str(run_root)],
                stdout=stdout,
                stderr=stderr,
            )
        finally:
            os.chdir(previous)

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn('"run_id":"fixture-run"', stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
