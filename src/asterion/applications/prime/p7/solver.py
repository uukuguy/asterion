"""P7 research admission and short plans over the single existing Broker."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from threading import RLock

from .research import ResearchWorkspace, copy_json, identifier
from .score import canonical_bytes, digest, score_planning_facts
from .solver_events import build_solver_payload
from .verified_history import validate_prediction
from .dynamic_evidence import EvidenceProcessingError
from .processing_diagnostics import DiagnosticLog
from .view_change import view_change


class Solver:
    def __init__(
        self,
        *,
        broker,
        kernel,
        control,
        workspace_root: Path,
        run_id: str,
        attempt_id: str,
        event_sink,
        experience=None,
        diagnostics=None,
        learner_profile='legacy',
    ):
        if learner_profile not in {'legacy', 'notes', 'autonomous'}:
            raise ValueError('research learner profile invalid')
        self.learner_profile = learner_profile
        self.broker, self.kernel, self.control = broker, kernel, control
        self.run_id, self.attempt_id = identifier(run_id), identifier(attempt_id)
        game = broker.game
        self._workspace = ResearchWorkspace(
            root=workspace_root,
            kernel=kernel,
            scope={
                "game_id": game.game_id,
                "seed": game.seed,
                "win_levels": game.win_levels,
                "run_id": run_id,
                "attempt_id": attempt_id,
            },
        )
        self._sink = event_sink
        self._experience = experience
        self._plans = {}
        self._lock = RLock()
        self._needs_calibration = self._workspace.loaded and learner_profile != 'autonomous'
        self._needs_revision = learner_profile != 'autonomous'
        self._revision_reason = "initial" if self._needs_revision else None
        self._environment_uncertain = False
        self._active_task = None
        self._cell_tasks = {}
        self._finished_cells = set()
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticLog(workspace_root.parent / "processing-diagnostics.json")
        self._processing_blocked = False

    def _observation(self) -> tuple[dict, dict]:
        full = self.broker.observation_state().to_projection()
        complete = self.broker.observation_reference()
        observation = {
            key: copy_json(full[key])
            for key in (
                "available_actions",
                "levels_completed",
                "state",
                "win_levels",
                "input_kind",
            )
        }
        frame = full["frame"]
        observation["frame"] = (
            [copy_json(frame[-1])]
            if isinstance(frame[0][0], list)
            else copy_json(frame)
        )
        observation["animation_ref"] = copy_json(complete["animation_ref"])
        observation["animation_paged"] = bool(complete["animation_ref"] and complete["animation_ref"]["frame_count"] > 1)
        for key in ("hud", "timers", "resources", "entities", "relations", "events"):
            if len(canonical_bytes(full[key])) <= 2048:
                observation[key] = copy_json(full[key])
        if observation != full:
            observation["projection_truncated"] = True
        sequence = complete["sequence"]
        reference = {
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "level": min(
                observation["levels_completed"] + 1, self.broker.game.win_levels
            ),
            "sequence": sequence,
            "observation_sha256": complete["observation_sha256"],
        }
        return observation, reference

    def current_context(self) -> dict:
        with self._lock:
            current = self._workspace.read()
            observation, reference = self._observation()
            if self._active_task is not None:
                current["task"] = copy_json(self._active_task)
            context = {
                **current,
                "observation": observation,
                "observation_ref": reference,
                "budget": self._budget(),
                "lifecycle": copy_json(self.control.snapshot()),
                "requires_calibration": self._needs_calibration if self.learner_profile != 'autonomous' else False,
                "needs_revision": self._needs_revision if self.learner_profile != 'autonomous' else False,
                "revision_reason": self._revision_reason if self.learner_profile != 'autonomous' else None,
                "environment_result_unknown": self._environment_uncertain,
                "processing_blocked": self._processing_blocked,
                "diagnostics": self.diagnostics.projection()[-8:],
                "checkpoint": self._workspace.checkpoint_manifest(),
            }
            if self._experience is not None:
                context["experience"] = self._experience.context()
            if self.learner_profile in {'notes', 'autonomous'} or 'notes' in current:
                context['learner_profile'] = self.learner_profile
                context['notes_boundary'] = self._notes_boundary(reference)
                context['notes_current'] = (
                    'notes' in current
                    and current['notes']['boundary'] == context['notes_boundary']
                    and not self._needs_revision and not self._needs_calibration
                )
            return self._bound_context(context)

    def _notes_boundary(self, reference):
        return {'level': reference['level'],
                'reset_sequence': next((item.sequence for item in reversed(self.broker.journal)
                                        if item.action == 'RESET'), 0),
                'kernel_generation': str(self.kernel.generation)}

    @staticmethod
    def _bound_context(context: dict) -> dict:
        limit = 128 * 1024 if 'notes' in context else 56 * 1024
        def size(value):
            if 'notes' in value:
                return len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                      separators=(',', ':')).encode('utf-8'))
            return len(canonical_bytes(value))
        if size(context) <= limit:
            return context
        context = copy_json(context)
        context["projection_truncated"] = True
        world = context["worldmap"]
        world["description_zh"] = world["description_zh"][:4000]
        world["state_summary"] = world["state_summary"][:300]
        for key in ("rules", "unknowns", "competing_hypotheses"):
            world[key] = [v[:300] for v in world[key][:8]]
        for key in ("changed", "retained"):
            context["correction"][key] = [
                v[:300] for v in context["correction"][key][:8]
            ]
        context["model"]["assumptions"] = [
            v[:300] for v in context["model"]["assumptions"][:8]
        ]
        context["task"]["obstacles"] = [
            v[:300] for v in context["task"]["obstacles"][:8]
        ]
        context["reports"] = context["reports"][:8]
        if size(context) > limit:
            world["description_zh"] = world["description_zh"][:1000]
            for key in (
                "hud",
                "timers",
                "resources",
                "entities",
                "relations",
                "events",
            ):
                context["observation"].pop(key, None)
        if size(context) > limit:
            world["description_zh"] = world["description_zh"][:500]
            for key in ("rules", "unknowns", "competing_hypotheses"):
                world[key] = [v[:150] for v in world[key][:2]]
            for key in ("changed", "retained"):
                context["correction"][key] = [
                    v[:150] for v in context["correction"][key][:2]
                ]
            context["model"]["assumptions"] = [
                v[:150] for v in context["model"]["assumptions"][:2]
            ]
            context["task"]["obstacles"] = [
                v[:150] for v in context["task"]["obstacles"][:2]
            ]
            context["reports"] = context["reports"][:4]
        if size(context) > limit:
            world["description_zh"] = world["description_zh"][:256]
            world["state_summary"] = world["state_summary"][:64]
            for key in ("rules", "unknowns", "competing_hypotheses"):
                world[key] = [v[:64] for v in world[key][:2]]
            for key in ("changed", "retained"):
                context["correction"][key] = [
                    v[:64] for v in context["correction"][key][:2]
                ]
            context["model"]["coverage"] = context["model"]["coverage"][:64]
            context["model"]["assumptions"] = [
                v[:64] for v in context["model"]["assumptions"][:2]
            ]
            for key in ("goal", "question", "public_basis"):
                context["task"][key] = context["task"][key][:64]
            context["task"]["obstacles"] = [
                v[:64] for v in context["task"]["obstacles"][:2]
            ]
            context["reports"] = context["reports"][:2]
        if size(context) > limit:
            raise ValueError("actor context too large")
        return context

    @staticmethod
    def _plan_projection(result: dict) -> dict:
        projected = copy_json(result)
        if len(canonical_bytes(projected)) <= 60 * 1024:
            return projected
        projected["projection_truncated"] = True
        for feedback in [*projected["feedback"], *projected.get("precondition_feedback", [])]:
            cells = feedback["expected"].get("cells", [])
            if len(cells) > 8:
                feedback["expected"]["cells"] = cells[:8]
                omitted_key = "before_cells_omitted" if "status" in feedback else "expect_cells_omitted"
                feedback[omitted_key] = len(cells) - 8
            differences = feedback.get("differences", [])
            if len(differences) > 8:
                feedback["differences"] = differences[:8]
                feedback["differences_omitted"] = len(differences) - 8
        for step in [
            *projected["unexecuted_steps"],
            *([projected["uncertain_step"]] if "uncertain_step" in projected else []),
        ]:
            cells = step["expect"].get("cells", [])
            if len(cells) > 8:
                step["expect"]["cells"] = cells[:8]
                step["expect_cells_omitted"] = len(cells) - 8
            before_cells = step.get("before", {}).get("cells", [])
            if len(before_cells) > 8:
                step["before"]["cells"] = before_cells[:8]
                step["before_cells_omitted"] = len(before_cells) - 8
        if len(canonical_bytes(projected)) > 60 * 1024:
            # Compact only the model-facing copy. Full measurements remain in
            # the recorded plan and can be recomputed from these exact frames.
            measurement_fields = {'origin', 'status', 'dx', 'dy', 'exposed_windows',
                                  'interpretation', 'before_observation_ref', 'after_observation_ref'}
            for feedback in projected['feedback']:
                measurement = feedback.get('view_change')
                if measurement is None:
                    continue
                compact = {key: value for key, value in measurement.items() if key in measurement_fields}
                compact['measurement_fields_omitted'] = len(measurement) - len(compact)
                compact['measurement_read'] = {
                    'read_api': 'p7_research.view_change',
                    'before_sequence': measurement['before_observation_ref']['sequence'],
                    'after_sequence': measurement['after_observation_ref']['sequence'],
                }
                feedback['view_change'] = compact
        if len(canonical_bytes(projected)) > 60 * 1024:
            # A long legal run ID, full predictions and before assertions can
            # still fill the response. Keep one representative assertion/diff
            # with cumulative omission counts; never trim committed references.
            for feedback in [*projected['feedback'], *projected.get('precondition_feedback', [])]:
                cells = feedback['expected'].get('cells', [])
                if len(cells) > 1:
                    omitted_key = 'before_cells_omitted' if 'status' in feedback else 'expect_cells_omitted'
                    feedback[omitted_key] = feedback.get(omitted_key, 0) + len(cells) - 1
                    feedback['expected']['cells'] = cells[:1]
                differences = feedback.get('differences', [])
                if len(differences) > 1:
                    feedback['differences_omitted'] = feedback.get('differences_omitted', 0) + len(differences) - 1
                    feedback['differences'] = differences[:1]
        if len(canonical_bytes(projected)) > 60 * 1024:
            projected["observation"] = {
                key: value
                for key, value in projected["observation"].items()
                if key
                in {
                    "frame",
                    "available_actions",
                    "state",
                    "levels_completed",
                    "win_levels",
                }
            }
        if len(canonical_bytes(projected)) > 60 * 1024:
            raise ValueError("actor feedback too large")
        return projected

    def _budget(self) -> dict:
        try:
            status = self.broker.status()
        except Exception:
            status = self.broker.terminal_snapshot().status
        wall_budget = getattr(self.control, 'budget_snapshot', None)
        return {
            "actions_remaining": status.actions_remaining,
            "primitive_actions": status.primitive_actions,
            "terminal_reason": status.terminal_reason,
            "target_level": self.broker.game.target_level,
            "action_cap": self.broker.game.action_cap,
            "scoring": score_planning_facts(self.broker.game, self.broker.journal,
                primitive_actions=status.primitive_actions, levels_completed=status.levels_completed),
            "scope": {
                "execution_controls": "host-run",
                "scoring_costs": "level-cumulative-including-resets",
                "state_restore_refunds_paid_actions": False,
                "environment_resources": "not-reported-by-adapter",
            },
            **(wall_budget() if callable(wall_budget) else {}),
        }

    def artifact(self, export_id: str):
        return self._workspace.artifact(export_id)

    def checkpoint(self) -> dict | None:
        return self._workspace.checkpoint_manifest()

    def kernel_recovered(self) -> None:
        with self._lock:
            self._needs_calibration = self.learner_profile != 'autonomous'
            if self.learner_profile == 'notes':
                self._needs_revision = True
                self._revision_reason = 'kernel-recovered'

    def experience_event(self, summary: str) -> None:
        self._emit("compute_task", "operator", status="declared", operation="analyze",
                   goal="复核历史研究", obstacles=[], question="历史规则与反例是否适用于当前观察？",
                   summary=summary, elapsed_ms=None, completed_units=None)

    def _emit(self, kind: str, origin: str, **fields) -> None:
        observation, reference = self._observation()
        event_task_id = fields.pop("_event_task_id", self._workspace.task_id)
        payload = build_solver_payload(
            kind,
            source_action_sequence=reference["sequence"],
            observation_sha256=reference["observation_sha256"],
            level=reference["level"],
            workspace_revision=self._workspace.revision,
            task_id=event_task_id,
            origin=origin,
            **fields,
        )
        try:
            self._sink(kind, payload)
        except Exception:
            # Keep failures visible even when the display sink itself is broken.
            self.diagnostics.record({
                "diagnostic_id": f"console-publication-failed:derived-failed:{reference['sequence']}",
                "code": "console-publication-failed", "severity": "warning",
                "stage": "derived-failed", "action_sequence": reference["sequence"],
                "outcome_known": True, "durable": False, "observed": None,
                "limit": None, "unit": None, "recovery": "read-only-rebuild",
            })

    def _processing_failure(self, error):
        self._processing_blocked = True
        self._environment_uncertain = not error.outcome_known
        diagnostic = self.diagnostics.record(error.diagnostic)
        try:
            self._sink("diagnostic", diagnostic)
        except Exception:
            # The independent diagnostic log remains available in context/summary.
            pass
        request = getattr(self.control, "request", None)
        if callable(request):
            request("stop", "processing-unavailable")
        return diagnostic

    def _focus_event(
        self, status: str, *, origin: str, elapsed_ms=None, summary="", task_id=None
    ):
        focused = self._active_task or self._workspace.read()["task"]
        self._emit(
            "compute_task",
            origin,
            status=status,
            operation=focused["next_operation"],
            goal=focused["goal"],
            obstacles=focused["obstacles"],
            question=focused["question"],
            summary=summary,
            elapsed_ms=elapsed_ms,
            completed_units=None,
            **({"_event_task_id": task_id} if task_id is not None else {}),
        )

    def kernel_event(self, kind: str, payload: Mapping) -> None:
        with self._lock:
            statuses = {
                "cell_started": "started",
                "cell_finished": "completed",
                "cell_interrupted": "interrupted",
                "kernel_lost": "interrupted",
            }
            if kind not in statuses:
                return
            if kind == "kernel_lost":
                self._needs_calibration = True
            cell_key = (payload.get("generation"), payload.get("call_id"))
            if not all(type(v) is str for v in cell_key):
                return
            if cell_key in self._finished_cells:
                return
            cell_task = self._cell_tasks.setdefault(
                cell_key, digest({"generation": cell_key[0], "call_id": cell_key[1]})
            )
            status = statuses[kind]
            if kind == "cell_finished" and payload.get("execution_status") != "ok":
                status = "failed"
            self._focus_event(
                status,
                origin="calculation",
                elapsed_ms=payload.get("elapsed_ms"),
                task_id=cell_task,
            )
            if kind != "cell_started":
                self._finished_cells.add(cell_key)

    def workspace(self, request: Mapping) -> dict:
        with self._lock:
            try:
                value = copy_json(request)
                if type(value) is not dict or "op" not in value:
                    raise ValueError
                op = value["op"]
                if op in {'context_archive_list', 'context_archive_read'}:
                    # Native session entries exist only in the selected Pi
                    # adapter. Direct Python RPC cannot discover other sessions
                    # or synthesize their cursors; this path has no side effects.
                    return {'status': 'rejected', 'reason': 'native-session-required'}
                if op == "read" and set(value) <= {"op", "revision"}:
                    current = self.current_context()
                    if "revision" in value:
                        current.update(self._workspace.read(value["revision"]))
                    return self._bound_context(current)
                if op == 'notes_read' and set(value) <= {'op', 'revision'}:
                    return {'status': 'ok', 'notes': self._workspace.notes_read(value.get('revision'))}
                if op == 'notes_history' and set(value) <= {'op', 'start', 'limit'}:
                    return {'status': 'ok', **self._workspace.notes_history(
                        start=value.get('start', 0), limit=value.get('limit', 16))}
                if op == 'notes' and set(value) == {'op', 'base_revision', 'observation_ref', 'text'}:
                    reference = self._observation()[1]
                    if (canonical_bytes(value['observation_ref']) != canonical_bytes(reference)
                            or not self.control.action_allowed()
                            or getattr(self.kernel, 'lost', False)
                            or self._environment_uncertain or self._processing_blocked):
                        raise ValueError
                    revised = self._workspace.save_notes(
                        base_revision=value['base_revision'], observation_ref=reference,
                        boundary=self._notes_boundary(reference), text=value['text'])
                    if self.learner_profile == 'notes':
                        self._needs_revision = False
                        self._needs_calibration = False
                        self._revision_reason = None
                    return {'status': 'noted', 'workspace_revision': revised['workspace_revision'],
                            'notes_revision': revised['notes_revision'], 'observation_ref': reference,
                            'needs_revision': self._needs_revision, 'revision_reason': self._revision_reason,
                            'requires_calibration': self._needs_calibration}
                if op == "focus" and set(value) == {"op", "task"}:
                    focused = self._workspace.focus(value["task"])
                    self._active_task = focused["task"]
                    self._focus_event(
                        "declared",
                        origin="actor",
                        summary=focused["task"]["public_basis"],
                    )
                    focused_result = {
                        "status": "focused",
                        **focused,
                        "workspace_revision": self._workspace.revision,
                    }
                    if len(canonical_bytes(focused_result)) > 16 * 1024:
                        focused_result["task"] = copy_json(focused["task"])
                        focused_result["task"]["obstacles"] = [
                            v[:300] for v in focused["task"]["obstacles"][:8]
                        ]
                        focused_result["projection_truncated"] = True
                    return focused_result
                latest = self._observation()[1]["sequence"]
                if op == "revise" and set(value) == {
                    "op",
                    "base_revision",
                    "worldmap",
                    "task",
                    "evidence_sequences",
                    "correction",
                }:
                    revised = self._workspace.revise(value, latest=latest)
                    self._accept_revision(revised, latest)
                    return {"status": "revised", **self.current_context()}
                if op == "publish" and set(value) == {
                    "op",
                    "base_revision",
                    "draft_export_id",
                }:
                    published = self._workspace.publish(
                        base_revision=value["base_revision"],
                        draft_export_id=value["draft_export_id"],
                        latest=latest,
                        verify_report=self._verify_report,
                    )
                    self._accept_revision(published, latest)
                    return {"status": "published", **self.current_context()}
                if (
                    op == "checkpoint"
                    and {"op", "revision", "analyzed_through"} <= set(value)
                    and set(value)
                    <= {
                        "op",
                        "revision",
                        "analyzed_through",
                        "state_export_id",
                        "frontier_export_id",
                    }
                ):
                    manifest = self._workspace.checkpoint(
                        value, latest=latest, generation=self.kernel.generation
                    )
                    return {"status": "checkpointed", "checkpoint": manifest}
                raise ValueError
            except (ValueError, TypeError, KeyError, AttributeError, OSError):
                return {
                    "status": "rejected",
                    "reason": "invalid-workspace-request",
                    "workspace_revision": self._workspace.revision,
                }

    def _accept_revision(self, revised: dict, latest: int) -> None:
        world, model, correction = (
            revised["worldmap"],
            revised["model"],
            revised["correction"],
        )
        # Program/model updates cannot stand in for fresh notes at a changed
        # learning boundary. The default legacy profile retains its old gate.
        if self.learner_profile == 'legacy':
            if (
                world["description_zh"].strip()
                and revised["task"]["goal"].strip()
                and latest in revised["evidence_sequences"]
                and not getattr(self.kernel, "lost", False)
            ):
                self._needs_revision = False
                self._revision_reason = None
                self._needs_calibration = False
            else:
                self._needs_revision = True
                self._revision_reason = self._revision_reason or "initial"
        self._active_task = revised["task"]
        self._workspace.focus(revised["task"])
        self._focus_event(
            "declared", origin="actor", summary=revised["task"]["public_basis"]
        )
        self._emit(
            "model_revision",
            "actor",
            revision=revised["workspace_revision"],
            parent_revision=revised["parent_revision"],
            description_zh=world["description_zh"],
            state_summary=world["state_summary"],
            rule_summaries=world["rules"],
            unknowns=world["unknowns"],
            coverage_summary=model["coverage"],
            validation_summary=self._validation_summary(revised["reports"]),
            correction_summary="；".join(correction["changed"]),
            evidence_sequences=revised["evidence_sequences"],
            **({'action_labels': world['action_labels']} if 'action_labels' in world else {}),
        )
        if self._experience is not None:
            exports = []
            for eid in revised["model"]["source_export_ids"]:
                exports.append({"export_id": eid, "kind": "text", "value": self._workspace.artifact(eid)})
            self._experience.record_revision(revised["workspace_revision"], correction, exports)

    @staticmethod
    def _validation_summary(reports):
        return (
            "历史报告核对（只对应原报告证据，不认证新语义）："
            + "；".join(
                f"{report['kind']}：{report['validation']['status']}，已核对{report['validation']['checked_count']}项"
                for report in reports
            )
            if reports
            else "尚无可核对的程序报告，目标与覆盖保持未知。"
        )

    def _verify_report(
        self, kind: str, value: object, evidence_sequences: list[int]
    ) -> dict:
        validation = {
            "kind": kind,
            "status": "unknown",
            "checked_count": 0,
            "comparison_count": 0,
            "first_counterexample_sequence": None,
        }
        if (
            type(value) is not dict
            or type(value.get("predictions")) is not list
            or not 1 <= len(value["predictions"]) <= 128
        ):
            return validation
        if kind == "search":
            # A search output is a candidate; matching historical states does not verify its route.
            return validation
        predictions = value["predictions"]
        try:
            if any(
                type(p) is not dict
                or set(p) != {"sequence", "expect"}
                or type(p["sequence"]) is not int
                for p in predictions
            ):
                return validation
            sequences = [p["sequence"] for p in predictions]
            if len(set(sequences)) != len(sequences) or not set(sequences) <= set(
                evidence_sequences
            ):
                return validation
            prepared = []
            for prediction in sorted(predictions, key=lambda p: p["sequence"]):
                sequence, expect = prediction["sequence"], prediction["expect"]
                if (
                    type(expect) is not dict
                    or not expect
                    or not set(expect)
                    <= {"cells", "frame_sha256", "state", "levels_completed"}
                ):
                    return validation
                if kind == "goal" and expect.get("state") not in {"WIN", "GAME_OVER"}:
                    return validation
                if kind == "dynamics" and sequence == 0:
                    return validation
                record = self.broker.history(sequence, 1)[0]
                if record["sequence"] != sequence:
                    return validation
                observation = {
                    "frame": self.broker.frame_at(sequence),
                    "state": record["state"],
                    "levels_completed": record["levels_completed"],
                }
                cells = expect.get("cells", [])
                if "cells" in expect and (
                    type(cells) is not list or not 1 <= len(cells) <= 128
                ):
                    return validation
                for cell in cells:
                    validate_prediction(
                        {
                            "action": {"name": "ACTION1", "data": {}},
                            "expect": {"cell": cell},
                        },
                        current_levels=0,
                    )
                for field in ("frame_sha256", "state"):
                    if field in expect:
                        # Validation only: pair NOT_FINISHED with a valid cell so it stays an assertion.
                        predicate = {field: expect[field]}
                        if field == "state" and expect[field] == "NOT_FINISHED":
                            predicate["cell"] = {"x": 0, "y": 0, "value": 0}
                        validate_prediction(
                            {
                                "action": {"name": "ACTION1", "data": {}},
                                "expect": predicate,
                            },
                            current_levels=0,
                        )
                if "levels_completed" in expect and (
                    type(expect["levels_completed"]) is not int
                    or not 0
                    <= expect["levels_completed"]
                    <= self.broker.game.win_levels
                ):
                    return validation
                if not cells and not {"frame_sha256", "state"} & set(expect):
                    return validation
                prepared.append((sequence, expect, observation))
            for sequence, expect, observation in prepared:
                validation["comparison_count"] += 1
                mismatch, differences = self._compare(expect, observation)
                if differences:
                    validation["status"] = "counterexample"
                    validation["first_counterexample_sequence"] = sequence
                    return validation
                validation["checked_count"] += 1
            validation["status"] = "checked"
        except (ValueError, KeyError, TypeError, IndexError):
            return {
                "kind": kind,
                "status": "unknown",
                "checked_count": 0,
                "comparison_count": 0,
                "first_counterexample_sequence": None,
            }
        return validation

    def _validate_plan(self, plan: dict, context: dict) -> list[dict]:
        fields = {
            "plan_id",
            "start",
            "workspace_revision",
            "goal",
            "purpose",
            "assumptions",
            "steps",
        }
        if self.learner_profile == 'autonomous':
            fields.update({'stop_on_mismatch', 'stop_on_view_change'})
        if set(plan) != fields:
            raise ValueError
        identifier(plan["plan_id"])
        start = plan["start"]
        if (
            type(start) is not dict
            or set(start)
            != {"run_id", "attempt_id", "level", "sequence", "observation_sha256"}
            or type(start["level"]) is not int
            or type(start["sequence"]) is not int
        ):
            raise ValueError
        if (
            plan["start"] != context["observation_ref"]
            or plan["workspace_revision"] != self._workspace.revision
            or (self.learner_profile != 'autonomous' and (self._needs_calibration or self._needs_revision))
            or self._environment_uncertain
            or self._processing_blocked
            or (self.learner_profile != 'autonomous' and getattr(self.kernel, "lost", False))
            or (self.learner_profile == 'notes' and not context.get('notes_current', False))
        ):
            raise ValueError
        if (
            type(plan["goal"]) is not str
            or len(plan["goal"]) > 600
            or plan["purpose"] not in {"advance", "probe"}
        ):
            raise ValueError
        if (
            type(plan["assumptions"]) is not list
            or len(plan["assumptions"]) > 32
            or any(type(v) is not str or len(v) > 600 for v in plan["assumptions"])
        ):
            raise ValueError
        if type(plan["steps"]) is not list or not 1 <= len(plan["steps"]) <= 20:
            raise ValueError
        translated = []
        autonomous = self.learner_profile == 'autonomous'
        if autonomous and type(plan['stop_on_mismatch']) is not bool:
            raise ValueError
        if autonomous and type(plan['stop_on_view_change']) is not bool:
            raise ValueError
        current_levels = context["observation"]["levels_completed"]
        for step in plan["steps"]:
            step_fields = {'action', 'expect', 'before'}
            if autonomous:
                step_fields.add('observe_after')
            if (type(step) is not dict or not {"action", "expect"} <= set(step)
                    or not set(step) <= step_fields):
                raise ValueError
            if 'observe_after' in step and type(step['observe_after']) is not bool:
                raise ValueError
            if "before" in step:
                before = step["before"]
                if type(before) is not dict or set(before) != {"cells"}:
                    raise ValueError
                self._validate_cells(before["cells"], step["action"], current_levels)
            expect = step["expect"]
            if (
                type(expect) is not dict
                or (not expect and not autonomous)
                or not set(expect)
                <= {"cells", "frame_sha256", "state", "levels_completed"}
            ):
                raise ValueError
            native_expect = {k: v for k, v in expect.items() if k != "cells"}
            if "cells" in expect:
                cells = expect["cells"]
                self._validate_cells(cells, step["action"], current_levels)
                # Validate the complete plan before dispatch. Grounding is
                # selected again from the actual observation at each step.
                native_expect["cell"] = cells[0]
            if "levels_completed" in native_expect:
                level = native_expect["levels_completed"]
                if (
                    type(level) is not int
                    or not 0 <= level <= self.broker.game.win_levels
                ):
                    raise ValueError
                if level <= current_levels:
                    # Broker only accepts progress witnesses; equality stays a host assertion.
                    del native_expect["levels_completed"]
            native = {"action": step["action"], "expect": native_expect}
            validate_prediction(native, current_levels=current_levels,
                                allow_unpredicted=autonomous, allow_nondistinguishing=autonomous)
            translated.append(native)
        return translated

    @staticmethod
    def _validate_cells(cells: object, action: dict, current_levels: int) -> None:
        if type(cells) is not list or not 1 <= len(cells) <= 128:
            raise ValueError
        coordinates = set()
        for cell in cells:
            validate_prediction(
                {"action": action, "expect": {"cell": cell}},
                current_levels=current_levels,
            )
            key = (cell["x"], cell["y"])
            if key in coordinates:
                raise ValueError
            coordinates.add(key)

    def _compare(self, expect: dict, observation: dict) -> tuple[str, list[dict]]:
        frame = observation["frame"]
        if frame and frame[0] and isinstance(frame[0][0], list):
            frame = frame[-1]
        differences = []
        for cell in expect.get("cells", []):
            x, y = cell["x"], cell["y"]
            actual = frame[y][x] if y < len(frame) and x < len(frame[y]) else None
            if actual != cell["value"]:
                differences.append(
                    {
                        "field": "cell",
                        "x": x,
                        "y": y,
                        "expected": cell["value"],
                        "actual": actual,
                    }
                )
        if "frame_sha256" in expect and digest(frame) != expect["frame_sha256"]:
            differences.append(
                {
                    "field": "frame_sha256",
                    "expected": expect["frame_sha256"],
                    "actual": digest(frame),
                }
            )
        for field in ("state", "levels_completed"):
            if field in expect and expect[field] != observation[field]:
                differences.append(
                    {
                        "field": field,
                        "expected": expect[field],
                        "actual": observation[field],
                    }
                )
        kind = "none"
        if differences:
            kind = (
                "goal"
                if all(v["field"] in {"state", "levels_completed"} for v in differences)
                else "state"
            )
        return kind, differences

    @staticmethod
    def _ground_prediction(native, cells, observation):
        grounded = copy_json(native)
        if cells:
            frame = observation["frame"][-1]
            grounded["expect"]["cell"] = copy_json(next(
                (cell for cell in cells if cell["y"] < len(frame)
                 and cell["x"] < len(frame[cell["y"]])
                 and frame[cell["y"]][cell["x"]] != cell["value"]),
                cells[0],
            ))
        return grounded

    def _probe_preparation(self, plan, translated, index, reference, observation=None):
        if (plan["purpose"] != "probe" or index + 1 >= len(translated)
                or translated[index]["action"]["name"] != "ACTION6"):
            return None
        observation = self._observation()[0] if observation is None else observation
        following = self._ground_prediction(
            translated[index + 1], plan["steps"][index + 1]["expect"].get("cells"),
            observation,
        )
        return {
            "run_id": self.run_id, "level": reference["level"],
            "sequence": reference["sequence"],
            "observation_sha256": reference["observation_sha256"],
            "next_prediction": following,
        }

    def execute_plan(self, plan: Mapping) -> dict:
        with self._lock:
            try:
                value = copy_json(plan)
                if type(value) is not dict:
                    raise ValueError
                plan_id = identifier(value.get("plan_id"))
                plan_digest = digest(value)
                if plan_id in self._plans:
                    previous = self._plans[plan_id]
                    if previous["digest"] != plan_digest:
                        raise ValueError
                    return self._plan_projection(previous["result"])
                context = self.current_context()
                if self.learner_profile == 'autonomous':
                    if not {'plan_id', 'start', 'steps'} <= set(value) <= {
                        'plan_id', 'start', 'steps', 'workspace_revision', 'goal',
                        'purpose', 'assumptions', 'stop_on_mismatch', 'stop_on_view_change',
                    }:
                        raise ValueError
                    value.setdefault('workspace_revision', self._workspace.revision)
                    value.setdefault('goal', '')
                    value.setdefault('purpose', 'advance')
                    value.setdefault('assumptions', [])
                    value.setdefault('stop_on_mismatch', True)
                    value.setdefault('stop_on_view_change', True)
                    if type(value['steps']) is not list:
                        raise ValueError
                    for step in value['steps']:
                        if type(step) is not dict:
                            raise ValueError
                        step.setdefault('expect', {})
                translated = self._validate_plan(value, context)
            except (ValueError, TypeError, KeyError, AttributeError):
                return {
                    "status": "rejected",
                    "reason": "processing-unavailable" if self._processing_blocked else ('notes-revision-required' if self.learner_profile == 'notes' else "worldmap-revision-required")
                    if self._needs_revision
                    else "invalid-actor-plan",
                    "needs_revision": self._needs_revision,
                    "revision_reason": self._revision_reason,
                    "observation_ref": self._observation()[1],
                    "requires_calibration": self._needs_calibration,
                    "workspace_revision": self._workspace.revision,
                    "diagnostics": self.diagnostics.projection(),
                }
            observation, reference = self._observation()
            result = {
                "status": "recorded",
                "plan_id": plan_id,
                "applied_count": 0,
                "stop_reason": "unknown",
                "feedback": [],
                "unexecuted_steps": copy_json(value["steps"]),
                "observation": observation,
                "observation_ref": reference,
                "workspace_revision": self._workspace.revision,
            }
            # Register before dispatch: an uncertain submission can never execute twice.
            self._plans[plan_id] = {"digest": plan_digest, "result": result}
            actions = [step["action"] for step in value["steps"]]

            def emit_plan(status):
                self._emit(
                    "plan",
                    "actor",
                    plan_id=plan_id,
                    status=status,
                    goal=value["goal"],
                    assumptions=value["assumptions"],
                    actions=actions,
                    applied_count=result["applied_count"],
                    stop_reason=None
                    if status in {"proposed", "executing"}
                    else result["stop_reason"],
                )

            emit_plan("proposed")
            emit_plan("executing")
            stop_reason = "matched"
            all_predictions_matched = True
            unexecuted_start = 0
            for index, native in enumerate(translated):
                self.control.poll(
                    reference["sequence"], reference["observation_sha256"]
                )
                if not self.control.action_allowed():
                    stop_reason = self.control.snapshot().get("state", "stopped")
                    break
                before = value["steps"][index].get("before")
                if before is not None:
                    _, differences = self._compare(before, observation)
                    result.setdefault("precondition_feedback", []).append({
                        "step_index": index,
                        "status": "mismatch" if differences else "matched",
                        "expected": copy_json(before),
                        "actual": {
                            "frame_sha256": digest(observation["frame"][-1]),
                            "state": observation["state"],
                            "levels_completed": observation["levels_completed"],
                        },
                        "differences": differences,
                        "observation_ref": copy_json(reference),
                    })
                    if differences:
                        stop_reason = "precondition-mismatch"
                        unexecuted_start = index
                        break
                if not self.control.enter("action"):
                    stop_reason = self.control.snapshot().get("state", "stopped")
                    break
                before_levels = observation["levels_completed"]
                before_observation, before_reference = observation, copy_json(reference)
                reply_received = False
                step_settled = False
                count = 0
                dispatch_start = getattr(self.broker, "actions_dispatched", None)
                journal_start = len(self.broker.journal)
                try:
                    native = self._ground_prediction(
                        native, value["steps"][index]["expect"].get("cells"), observation,
                    )
                    preparation = (self._probe_preparation(value, translated, index, reference, observation)
                                   if self.learner_profile != 'autonomous' else None)
                    if preparation:
                        dispatched = self.broker.act_checked([native], probe_preparation=preparation)
                    else:
                        dispatched = self.broker.act_checked([native])
                    reply_received = True
                    count = dispatched["applied_count"]
                    if type(count) is not int or count not in (0, 1):
                        raise ValueError
                    result["applied_count"] += count
                    unexecuted_start = result["applied_count"]
                    observation, reference = self._observation()
                    expectation = value['steps'][index]['expect']
                    prediction_present = bool(expectation)
                    all_predictions_matched = all_predictions_matched and prediction_present
                    mismatch_kind, differences = (
                        self._compare(expectation, observation)
                        if count and prediction_present
                        else ("unknown", [])
                    )
                    all_predictions_matched = all_predictions_matched and not differences
                    native_reason = dispatched.get("stop_reason", "unknown")
                    feedback = {
                        "step_index": index,
                        "expected": copy_json(value["steps"][index]["expect"]),
                        "prediction_present": prediction_present,
                        "actual": {
                            "frame_sha256": digest(observation["frame"][-1]),
                            "state": observation["state"],
                            "levels_completed": observation["levels_completed"],
                        },
                        "differences": differences,
                        "mismatch_kind": mismatch_kind,
                        "counterexample_sequence": reference["sequence"]
                        if differences
                        else None,
                        "observation_ref": reference,
                    }
                    result["feedback"].append(feedback)
                    self._emit(
                        "feedback",
                        "environment",
                        plan_id=plan_id,
                        expected_summary="核对计划中的关键像素、状态和关卡预测。" if prediction_present else "本步未提供预测。",
                        actual_summary="预测与真实观察一致。"
                        if mismatch_kind == "none"
                        else "真实观察与预测有差异。" if prediction_present else "已返回真实观察，未判定预测匹配。",
                        mismatch_kind=mismatch_kind,
                        unexecuted_count=len(actions) - result["applied_count"],
                        counterexample_sequence=feedback["counterexample_sequence"],
                    )
                    continue_mismatch = self.learner_profile == 'autonomous' and not value['stop_on_mismatch']
                    if observation["state"] in {"WIN", "GAME_OVER"}:
                        stop_reason = (
                            "win" if observation["state"] == "WIN" else "game-over"
                        )
                    elif observation["levels_completed"] > before_levels:
                        stop_reason = "level-advanced"
                    elif count and native["action"]["name"] == "RESET":
                        stop_reason = "reset-applied"
                    elif differences and not continue_mismatch:
                        stop_reason = "prediction-mismatch"
                    elif native_reason not in {'matched', 'executed'} and not (
                        continue_mismatch and native_reason == 'prediction-mismatch'
                    ):
                        stop_reason = native_reason
                    if count and self.learner_profile != 'autonomous':
                        reason = (
                            "reset-applied"
                            if native["action"]["name"] == "RESET"
                            else "level-advanced"
                            if observation["levels_completed"] > before_levels
                            else "prediction-mismatch"
                            if differences or native_reason == "prediction-mismatch"
                            else None
                        )
                        if reason is not None:
                            self._needs_revision = True
                            self._revision_reason = reason
                    self.control.poll(
                        reference["sequence"], reference["observation_sha256"]
                    )
                    if stop_reason == "matched" and not self.control.action_allowed():
                        stop_reason = self.control.snapshot().get("state", "stopped")
                    step_settled = True
                except EvidenceProcessingError as error:
                    # Derived work can fail after the broker durably committed
                    # its transition. Reconcile that one exact committed action;
                    # a received but uncommitted reply never acquires this count.
                    if error.outcome_known and error.durable and not reply_received:
                        journal = self.broker.journal
                        if (len(journal) == reference['sequence'] + 1
                                and journal[-1].sequence == error.diagnostic['action_sequence']
                                and journal[-1].action == native['action']['name']):
                            result['applied_count'] += 1
                            try:
                                observation, reference = self._observation()
                            except EvidenceProcessingError:
                                pass  # Keep the prior pixels, with the explicit processing fault.
                    stop_reason = "environment-result-unknown" if not error.outcome_known else "processing-failed"
                    self._processing_failure(error)
                    result["diagnostics"] = self.diagnostics.projection()
                    unexecuted_start = index if error.stage == 'not-dispatched' else index + 1
                    if not error.outcome_known:
                        result["uncertain_step_index"] = index
                        result["uncertain_step"] = copy_json(value["steps"][index])
                        result["feedback"].append({
                            "step_index": index, "mismatch_kind": "unknown",
                            "expected": copy_json(value["steps"][index]["expect"]),
                            "actual": None, "differences": [],
                            "counterexample_sequence": None, "observation_ref": reference,
                        })
                except Exception:
                    if (not reply_received and type(dispatch_start) is int
                            and getattr(self.broker, "actions_dispatched", None) == dispatch_start
                            and len(self.broker.journal) == journal_start):
                        # A local adapter rejection must not invent an engine
                        # call. An unchanged journal alone cannot prove this:
                        # calls with missing replies are absent from it too.
                        self._processing_failure(EvidenceProcessingError(
                            "action-not-dispatched", stage="not-dispatched",
                            action_sequence=reference["sequence"] + 1,
                            outcome_known=True,
                        ))
                        result["diagnostics"] = self.diagnostics.projection()
                        stop_reason = "processing-failed"
                        unexecuted_start = index
                        break
                    if reply_received:
                        error = EvidenceProcessingError(
                            "derived-projection-failed", stage="derived-failed",
                            action_sequence=reference["sequence"], outcome_known=True,
                            durable=True, recovery="read-only-rebuild",
                        )
                        self._processing_failure(error)
                        result["diagnostics"] = self.diagnostics.projection()
                        stop_reason = "processing-failed"
                        unexecuted_start = index + 1
                        break
                    stop_reason = "environment-result-unknown"
                    self._processing_failure(EvidenceProcessingError(
                        "engine-no-reply", stage="dispatched-no-reply",
                        action_sequence=reference["sequence"] + 1,
                        outcome_known=False,
                    ))
                    result["diagnostics"] = self.diagnostics.projection()
                    result["uncertain_step_index"] = index
                    result["uncertain_step"] = copy_json(value["steps"][index])
                    unexecuted_start = index + 1
                    result["feedback"].append(
                        {
                            "step_index": index,
                            "mismatch_kind": "unknown",
                            "expected": copy_json(value["steps"][index]["expect"]),
                            "actual": None,
                            "differences": [],
                            "counterexample_sequence": None,
                            "observation_ref": reference,
                        }
                    )
                    # Do not fabricate a returned action result or replay this plan.
                    self._emit(
                        "feedback",
                        "environment",
                        plan_id=plan_id,
                        expected_summary="等待真实动作结果。",
                        actual_summary="环境结果未确认，未执行后缀已停止。",
                        mismatch_kind="unknown",
                        unexecuted_count=len(actions) - unexecuted_start,
                        counterexample_sequence=None,
                    )
                finally:
                    self.control.leave("action")
                if self.learner_profile == 'autonomous' and step_settled and count == 1:
                    # Analysis is outside the action exception boundary: a failed
                    # measurement cannot turn a committed environment result unknown.
                    try:
                        measurement = view_change(before_observation['frame'][-1], observation['frame'][-1])
                        if (type(measurement) is not dict
                                or measurement.get('status') not in {'candidate', 'no-candidate', 'ambiguous', 'unsupported'}
                                or len(canonical_bytes(measurement)) > 2048):
                            raise ValueError('view measurement unavailable')
                    except Exception:
                        measurement = {'status': 'unavailable', 'reason': 'observation-analysis-unavailable'}
                    if measurement['status'] in {'candidate', 'unavailable'}:
                        feedback['view_change'] = {
                            **copy_json(measurement),
                            'origin': 'derived-pixel-measurement',
                            'before_observation_ref': before_reference,
                            'after_observation_ref': copy_json(reference),
                        }
                    # Poll again after releasing the action and doing analysis;
                    # operator controls and all native hard stops take priority.
                    self.control.poll(reference['sequence'], reference['observation_sha256'])
                    if stop_reason == 'matched' and not self.control.action_allowed():
                        stop_reason = self.control.snapshot().get('state', 'stopped')
                    if stop_reason == 'matched' and index + 1 < len(translated):
                        boundary_reason = (
                            'actor-checkpoint' if value['steps'][index].get('observe_after', False)
                            else 'view-change-candidate' if value['stop_on_view_change'] and measurement['status'] == 'candidate'
                            else 'observation-analysis-unavailable' if value['stop_on_view_change'] and measurement['status'] == 'unavailable'
                            else None
                        )
                        if boundary_reason is not None:
                            stop_reason = 'observation-boundary'
                            result['observation_boundary'] = {
                                'origin': 'application-policy',
                                'reason': boundary_reason, 'step_index': index,
                                'observation_ref': copy_json(reference),
                            }
                if stop_reason != "matched":
                    break
            result.update(
                stop_reason='executed' if stop_reason == 'matched' and not all_predictions_matched else stop_reason,
                observation=observation,
                observation_ref=reference,
                budget=self._budget(),
                needs_revision=self._needs_revision if self.learner_profile != 'autonomous' else False,
                revision_reason=self._revision_reason if self.learner_profile != 'autonomous' else None,
                unexecuted_steps=copy_json(value["steps"][unexecuted_start:]),
            )
            emit_plan("completed" if stop_reason == "matched" else "stopped")
            return self._plan_projection(result)
