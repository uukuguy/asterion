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
from asterion.capabilities.prime_arc_agi_3_solver import PrimeArcAgi3SolveReceipt
from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES
from asterion.applications import first_party_cli as asterion_cli
from asterion.applications.prime.p7.run_story import (
    RunStoryError,
    ArtifactApplication,
    analyze_bundle,
    compile_run,
    read_run_evidence,
    render_web,
    export_standalone,
)
from asterion.applications.prime.p7.run_story.operator_narrator import (
    RunStoryNarrator,
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
    grids: list[list[list[int]]], levels_completed: int, *, win_levels: int = 7
) -> str:
    return digest(
        {
            "available_actions": ("ACTION1", "ACTION2", "ACTION3", "ACTION4"),
            "frame": tuple(tuple(tuple(row) for row in grid) for grid in grids),
            "levels_completed": levels_completed,
            "state": "FINISHED" if levels_completed else "NOT_FINISHED",
            "win_levels": win_levels,
        }
    )


def _observation_digest(
    grid: list[list[int]], levels_completed: int, *, win_levels: int = 7
) -> str:
    return _observation_digest_frames(
        [grid], levels_completed, win_levels=win_levels
    )


def _recording_row(
    *,
    action: str,
    grid: list[list[int]],
    levels_completed: int,
    timestamp: str,
    animation: list[list[list[int]]] | None = None,
    action_data: dict[str, int] | None = None,
    win_levels: int = 7,
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "data": {
            "game_id": "fixture-game",
            "state": "FINISHED" if levels_completed else "NOT_FINISHED",
            "levels_completed": levels_completed,
            "win_levels": win_levels,
            "action_input": {
                "id": action,
                "data": {} if action_data is None else action_data,
                "reasoning": None,
            },
            "guid": "fixture-guid",
            "full_reset": action == "RESET",
            "available_actions": [1, 2, 3, 4],
            "frame": [grid] if animation is None else animation,
        },
    }


def write_completed_fixture(
    root: Path,
    *,
    worker_secret: str = "private",
    animated: bool = False,
    win_levels: int = 7,
    action_data: dict[str, int] | None = None,
    reset_during_run: bool = False,
    recovered: bool = False,
    modern_summary: bool = False,
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
    before_sha = _observation_digest(before, 0, win_levels=win_levels)
    steps = [("ACTION6" if action_data else "ACTION1", action_data or {}, animation, 1)]
    if reset_during_run:
        steps = [
            ("ACTION1", action_data or {}, [after], 0),
            ("RESET", {}, [before], 0),
            ("ACTION1", {}, animation, 1),
        ]
    recorder = PrimeTraceRecorder(trace_root)
    if recovered:
        recorder.append(
            "arc.recovery.source",
            P7_TRACE_IDENTITIES,
            {
                "recording_sha256s": ["a" * 64],
                "source_run_id": "source-run",
                "summary_sha256": "b" * 64,
                "trace_seal_sha256": "c" * 64,
                "trace_sha256": "d" * 64,
            },
        )
    previous_sha = before_sha
    for sequence, (action, data, grids, levels_completed) in enumerate(steps, start=1):
        current_sha = _observation_digest_frames(
            grids, levels_completed, win_levels=win_levels
        )
        payload: dict[str, object] = {
            "action": action,
            "after_sha256": current_sha,
            "before_sha256": previous_sha,
            "levels_completed": levels_completed,
            "sequence": sequence,
        }
        if data:
            payload["data"] = data
        recorder.append("arc.action", P7_TRACE_IDENTITIES, payload)
        previous_sha = current_sha
    recorder.append(
        "arc.usage.reported",
        P7_TRACE_IDENTITIES,
        {"input_tokens": 120, "output_tokens": 31},
    )
    recorder.append(
        "arc.run.completed",
        P7_TRACE_IDENTITIES,
        {
            "game_id": "fixture-game",
            "levels_completed": 1,
            "primitive_actions": len(steps),
            "replay_sha256": "sha256:" + "a" * 64,
            "seed": 0,
            "terminal_reason": "level-completed",
            "win_levels": win_levels,
        },
    )
    recorder.seal()
    rows = (
        _recording_row(
            action="RESET",
            grid=before,
            levels_completed=0,
            timestamp="2026-09-09T00:00:00+00:00",
            win_levels=win_levels,
        ),
        _recording_row(
            action="RESET",
            grid=before,
            levels_completed=0,
            timestamp="2026-09-09T00:00:00.001000+00:00",
            win_levels=win_levels,
        ),
        *(
            _recording_row(
                action=action,
                grid=grids[-1],
                levels_completed=levels_completed,
                timestamp=f"2026-09-09T00:00:0{sequence}+00:00",
                animation=grids,
                action_data=data,
                win_levels=win_levels,
            )
            for sequence, (action, data, grids, levels_completed) in enumerate(steps, start=1)
        ),
    )
    recording = recording_root / "fixture-game-guid.jsonl"
    recording.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    if not recovered:
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
    receipt = dict(
        vars(
            PrimeArcAgi3SolveReceipt.create(
                run_id="fixture-run",
                completed_level_count=1,
                primitive_action_count=len(steps),
                partial_game_score="3.571429",
            )
        )
    )
    receipt.pop("run_id")
    receipt["receipt_sha256"] = receipt["receipt_sha256"].removeprefix("sha256:")
    summary = {
        "schema": "asterion.prime.p7-live-private-summary/v1",
        "run_id": "fixture-run",
        "receipt": receipt,
        "broker": {
            "game_id": "fixture-game",
            "levels_completed": 1,
            "primitive_actions": len(steps),
            "replay_sha256": "sha256:" + "a" * 64,
            "seed": 0,
            "terminal_reason": "level-completed",
            "win_levels": win_levels,
        },
        "replay_verified": True,
        "sealed_trace": True,
        "cleanup_complete": True,
        "comparison_report": None,
        "reason": None,
        "failure": None,
        "diagnostics": (
            {
                "recovered_from": "source-run",
                "recovery_kind": "concurrent-trace-append",
                "source_hashes": {
                    "recording_sha256s": ["a" * 64],
                    "summary_sha256": "b" * 64,
                    "trace_seal_sha256": "c" * 64,
                    "trace_sha256": "d" * 64,
                },
                "source_usage_input_tokens": 120,
                "source_usage_output_tokens": 31,
                "usage_attributed_to_source": True,
                "worker_cell_count": 0,
            }
            if recovered
            else {"worker_cell_count": 1}
        ),
    }
    if not recovered:
        summary["completed_prefix"] = None
    if modern_summary:
        summary["experiment"] = {
            "action_cap": 25,
            "deadline_ms": None,
            "game_id": "fixture-game",
            "model": "deepseek-v4-flash",
            "prediction_variant": "verified",
            "seed": 0,
            "stall_seconds": None,
            "target_level": 1,
        }
        summary["prediction_accounting"] = {
            "checked_plan_errors": 0,
            "checked_plans": 0,
            "first_sequence": 0,
            "frame_queries": 1,
            "history_queries": 0,
            "history_records_returned": 0,
            "last_sequence": 1,
            "matched_expectations": 0,
            "mismatches": 0,
            "uncertain_items": 0,
            "unexecuted_items": 0,
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

    def test_reads_recording_with_nine_win_levels(self) -> None:
        evidence = read_run_evidence(write_completed_fixture(self.root, win_levels=9))

        self.assertEqual(evidence.game_id, "fixture-game")
        self.assertEqual(tuple(action.name for action in evidence.actions), ("ACTION1",))

    def test_accepts_current_completed_summary_shape(self) -> None:
        evidence = read_run_evidence(write_completed_fixture(self.root))

        self.assertEqual(evidence.levels_completed, 1)

    def test_accepts_modern_summary_metadata_without_relaxing_evidence(self) -> None:
        evidence = read_run_evidence(
            write_completed_fixture(self.root, modern_summary=True)
        )

        self.assertEqual(evidence.game_id, "fixture-game")
        self.assertEqual(len(evidence.actions), 1)

    def test_rejects_malformed_modern_summary_metadata(self) -> None:
        run_root = write_completed_fixture(self.root, modern_summary=True)
        summary_path = run_root / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["prediction_accounting"]["mismatches"] = "zero"
        summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")

        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)

    def test_accepts_click_data_only_when_recording_matches_trace(self) -> None:
        evidence = read_run_evidence(
            write_completed_fixture(self.root, action_data={"x": 12, "y": 34})
        )

        self.assertEqual(tuple(action.name for action in evidence.actions), ("ACTION6",))

    def test_rejects_click_data_mismatch_from_trace(self) -> None:
        run_root = write_completed_fixture(
            self.root, action_data={"x": 12, "y": 34}
        )
        recording = next((run_root / "recordings").glob("*/*.jsonl"))
        rows = [json.loads(line) for line in recording.read_text().splitlines()]
        rows[-1]["data"]["action_input"]["data"] = {"x": 12, "y": 35}
        recording.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)

    def test_accepts_reset_as_a_recorded_primitive_action(self) -> None:
        evidence = read_run_evidence(write_completed_fixture(self.root, reset_during_run=True))

        self.assertEqual(
            tuple(action.name for action in evidence.actions),
            ("ACTION1", "RESET", "ACTION1"),
        )

    def test_accepts_recovered_evidence_without_worker_reasoning_cells(self) -> None:
        evidence = read_run_evidence(write_completed_fixture(self.root, recovered=True))

        self.assertEqual(evidence.worker_cell_count, 0)
        self.assertEqual(evidence.reasoning_cells, ())
        self.assertNotIn("worker_cells", evidence.source_digests)

    def test_rejects_workerless_run_without_bound_recovery_provenance(self) -> None:
        run_root = write_completed_fixture(self.root, recovered=True)
        summary_path = run_root / "summary.json"
        summary = json.loads(summary_path.read_text())
        summary["diagnostics"]["recovered_from"] = "another-run"
        summary_path.write_text(json.dumps(summary, sort_keys=True), encoding="utf-8")

        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)

    def test_rejects_verified_summary_without_cleanup_or_valid_receipt(self) -> None:
        for field, value in (
            ("cleanup_complete", False),
            ("receipt_sha256", "0" * 64),
        ):
            with self.subTest(field=field):
                run_root = write_completed_fixture(self.root / field)
                summary_path = run_root / "summary.json"
                summary = json.loads(summary_path.read_text())
                if field == "receipt_sha256":
                    summary["receipt"][field] = value
                else:
                    summary[field] = value
                summary_path.write_text(
                    json.dumps(summary, sort_keys=True), encoding="utf-8"
                )

                with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
                    read_run_evidence(run_root)

    def test_rejects_recording_with_inconsistent_win_levels(self) -> None:
        run_root = write_completed_fixture(self.root, win_levels=9)
        recording = next((run_root / "recordings").glob("*/*.jsonl"))
        rows = [json.loads(line) for line in recording.read_text().splitlines()]
        rows[-1]["data"]["win_levels"] = 7
        recording.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)

    def test_rejects_recording_game_id_relabelled_from_sealed_identity(self) -> None:
        run_root = write_completed_fixture(self.root, win_levels=9)
        recording = next((run_root / "recordings").glob("*/*.jsonl"))
        rows = [json.loads(line) for line in recording.read_text().splitlines()]
        for row in rows:
            row["data"]["game_id"] = "relabelled-game"
        recording.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)

    def test_rejects_broker_replay_digest_mismatch_from_sealed_completion(self) -> None:
        run_root = write_completed_fixture(self.root, win_levels=9)
        summary = run_root / "summary.json"
        value = json.loads(summary.read_text())
        value["broker"]["replay_sha256"] = "sha256:" + "b" * 64
        summary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

        with self.assertRaisesRegex(RunStoryError, "evidence-invalid"):
            read_run_evidence(run_root)

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
        self.assertIsNone(run["action_limit"])
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

    def test_compiler_preserves_click_coordinates_in_action_data(self) -> None:
        bundle = compile_run(
            write_completed_fixture(self.root, action_data={"x": 12, "y": 34}),
            self.root / "artifacts" / "arc-agi-3",
        )

        action = json.loads(
            (bundle.run_root / "data" / "actions.jsonl").read_text().strip()
        )
        self.assertEqual(action["data"], {"x": 12, "y": 34})

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

    def test_operator_narrator_accepts_only_approved_flash_names(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from asterion.applications.prime.p7.run_story.operator_narrator import load_operator_narrator

        for model in ("deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-0731"):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".env").write_text(
                    f"ASTERION_PRIME_EXPERIMENT_MODEL={model}\nDEEPSEEK_API_KEY=sentinel-private-key\n",
                    encoding="utf-8",
                )
                session = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(final_text="{}")))
                with patch.dict(os.environ, {}, clear=True), patch(
                    "asterion.applications.prime.p7.run_story.operator_narrator.build_rpc_session",
                    return_value=session,
                ) as build:
                    try:
                        narrator = load_operator_narrator(root)
                    except RunStoryError:
                        self.fail(f"approved Flash model {model} was rejected")
                    build.assert_not_called()
                    self.assertEqual(narrator.model_id, model)
                    self.assertNotIn("sentinel-private-key", repr(narrator))
                    self.assertEqual(narrator._invoke("fixture prompt"), "{}")
                    config = build.call_args.kwargs
                    command = config["command"]
                    self.assertEqual(command[-4:], ("--provider", "deepseek", "--model", model))
                    self.assertEqual(config["deadline_seconds"], 300)
                    for flag in ("--no-tools", "--no-session", "--no-extensions", "--no-skills", "--no-context-files"):
                        self.assertIn(flag, command)
                    self.assertNotIn("sentinel-private-key", repr(command))
                    session.run.assert_awaited_once()

    def test_operator_narrator_rejects_unapproved_model_or_missing_key(self) -> None:
        from unittest.mock import patch
        from asterion.applications.prime.p7.run_story.operator_narrator import load_operator_narrator

        for model, key in (("deepseek-pro", "sentinel-private-key"), ("deepseek-flash", "")):
            with self.subTest(model=model, key_present=bool(key)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".env").write_text(
                    f"ASTERION_PRIME_EXPERIMENT_MODEL={model}\nDEEPSEEK_API_KEY={key}\n",
                    encoding="utf-8",
                )
                with patch.dict(os.environ, {}, clear=True), patch(
                    "asterion.applications.prime.p7.run_story.operator_narrator.build_rpc_session"
                ) as build:
                    with self.assertRaises(RunStoryError) as error:
                        load_operator_narrator(root)
                    self.assertEqual(str(error.exception), "narrator-unavailable")
                    build.assert_not_called()

    def test_pi_narrator_accepts_one_json_response_without_exposing_config(self) -> None:
        calls: list[str] = []
        narrator = RunStoryNarrator(
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

    def test_exports_one_self_contained_offline_html_file(self) -> None:
        artifact_root = self.root / "artifacts" / "arc-agi-3"
        bundle = compile_run(write_completed_fixture(self.root), artifact_root)
        analysis = analyze_bundle(bundle.run_root, _StubNarrator(_valid_story()))
        render = render_web(bundle.run_root, analysis.analysis_id)

        first = export_standalone(render.render_root, artifact_root / "exports")
        second = export_standalone(render.render_root, artifact_root / "exports")

        self.assertEqual(first.path, second.path)
        self.assertEqual(first.sha256, second.sha256)
        html = first.path.read_text(encoding="utf-8")
        self.assertNotIn('src="assets/', html)
        self.assertNotIn('href="assets/', html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("const __ASTERION_EMBEDDED__", html)
        self.assertIn("fixture-run", html)
        self.assertIn("一次受控移动验证", html)

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
