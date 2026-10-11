"""P7-only registered models and evidence over the existing Prime kernel."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import TimeoutError as FutureTimeout
import hashlib
import json
from pathlib import Path
import threading
from time import monotonic
import uuid
import zlib


# Appended to the read-only p7_research module; callbacks live in this kernel,
# never in a host-side simulator or an independently reconstructed model.
KERNEL_SOURCE = r'''
import zlib as _rollout_zlib
import base64 as _rollout_base64
import contextlib as _rollout_contextlib
import io as _rollout_io
import hashlib as _rollout_hashlib
_registered_rollout_model = None
_rollout_registration_sequence = 0
_rollout_calls = []
_rollout_call_sequence = 0
_rollout_call_depth = 0
_last_auto_rollout_result = None
_raw_rollout = rollout
_raw_replay_cases = replay_cases
_raw_evaluate_candidates = evaluate_candidates
_raw_replay_deaths = replay_deaths

def _rollout_boundary(ctx):
    ref = ctx['observation_ref']
    notes = ctx.get('notes_boundary', {})
    return {'run_id': ref['run_id'], 'attempt_id': ref['attempt_id'],
            'level': ref['level'], 'reset_sequence': notes.get('reset_sequence', 0)}

def register_rollout_model(*, from_frame, transition, settled, terminal,
                          risk_check=None, collision=None,
                          max_ticks_per_action=128, model_id='local'):
    """Explicitly publish this kernel's callbacks for host evaluation.

    Model names are labels, not immutable source versions. RESET/level changes
    invalidate registration. No callback is guessed from the actor globals.
    """
    global _registered_rollout_model, _rollout_registration_sequence
    if any(not callable(v) for v in (from_frame, transition, settled, terminal)):
        raise ValueError('model callbacks unavailable')
    if any(v is not None and not callable(v) for v in (risk_check, collision)):
        raise ValueError('model callbacks unavailable')
    if type(max_ticks_per_action) is not int or max_ticks_per_action <= 0:
        raise ValueError('model tick limit invalid')
    if type(model_id) is not str or not model_id or len(model_id) > 160:
        raise ValueError('model label invalid')
    boundary = _rollout_boundary(current())
    _rollout_registration_sequence += 1
    _registered_rollout_model = {'from_frame': from_frame, 'transition': transition,
        'settled': settled, 'terminal': terminal, 'risk_check': risk_check,
        'collision': collision, 'max_ticks_per_action': max_ticks_per_action,
        'model_id': model_id, 'registration_id': _rollout_registration_sequence,
        'boundary': boundary}
    return {'status': 'registered', 'model_id': model_id,
            'registration_id': _rollout_registration_sequence, 'boundary': boundary}

def _model_registration():
    model = _registered_rollout_model
    return None if model is None else {k: model[k] for k in ('model_id', 'registration_id', 'boundary')}

def _rollout_compact(result):
    risk = result.get('risk', {})
    if type(risk) is not dict:
        risk = {'status': risk}
    return {'status': result.get('status', 'evaluated'), 'risk': risk.get('status', 'unassessed'),
            'reason': result.get('reason', 'model-relative'), 'outcome': result.get('outcome'),
            'ticks': result.get('ticks', 0), 'coverage': risk.get('coverage'),
            'findings': risk.get('findings', []), 'execution_authority': 'none',
            'claims': 'model-relative'}

def _remember_rollout_call(operation, reference, candidates, result, registration=None, frame_sha256=None):
    global _rollout_call_sequence
    _rollout_call_sequence += 1
    _rollout_calls.append({'operation': operation, 'origin': 'actor',
        'call_sequence': _rollout_call_sequence,
        'observation_ref': _p7_rollout_copy(reference),
        'candidate_actions': _p7_rollout_copy(candidates),
        'registration': registration, 'frame_sha256': frame_sha256,
        'result': _rollout_compact(result)})

def _actor_rollout_call(operation, function, args, kwargs, candidates):
    global _rollout_call_depth
    reference = kwargs.pop('observation_ref', None)
    outer = _rollout_call_depth == 0
    # Arbitrary raw-helper states do not prove the registered initializer was
    # used. They remain real calls, but cannot cover a host candidate.
    registration = None
    _rollout_call_depth += 1
    try:
        result = function(*args, **kwargs)
        if outer:
            _remember_rollout_call(operation, reference, candidates, result, registration)
        return result
    except Exception:
        if outer:
            _remember_rollout_call(operation, reference, candidates,
                                  {'status': 'failed', 'risk': 'unassessed', 'reason': 'helper_call_failed'}, registration)
        raise
    finally:
        _rollout_call_depth -= 1

def rollout(initial_state, actions, **kwargs):
    """The pure helper plus an actual-call record; optional explicit ref binding."""
    return _actor_rollout_call('rollout', _raw_rollout, (initial_state, actions), kwargs, [actions])

def replay_cases(cases, **kwargs):
    return _actor_rollout_call('replay_cases', _raw_replay_cases, (cases,), kwargs,
                              [case.get('actions', []) for case in cases])

def evaluate_candidates(initial_state, candidates, **kwargs):
    return _actor_rollout_call('evaluate_candidates', _raw_evaluate_candidates,
                              (initial_state, candidates), kwargs, candidates)

def replay_deaths(**kwargs):
    return _actor_rollout_call('replay_deaths', _raw_replay_deaths, (), kwargs, [])

def _evaluate_registered(frame, reference, action, boundary):
    global _registered_rollout_model
    model = _registered_rollout_model
    if model is None:
        return {'status': 'not_evaluated', 'risk': 'unassessed', 'reason': 'model_missing', 'ticks': 0}, None
    if model['boundary'] != boundary:
        _registered_rollout_model = None
        return {'status': 'not_evaluated', 'risk': 'unassessed', 'reason': 'model_boundary_invalidated', 'ticks': 0}, None
    try:
        initial = model['from_frame'](_p7_rollout_copy(frame), _p7_rollout_copy(reference))
        result = _raw_rollout(initial, [action], transition=model['transition'],
            settled=model['settled'], terminal=model['terminal'],
            collision=model['collision'], max_ticks_per_action=model['max_ticks_per_action'],
            risk_check=model['risk_check'])
        return _rollout_compact(result), result
    except Exception:
        return {'status': 'not_evaluated', 'risk': 'unassessed', 'reason': 'model_callback_failed', 'ticks': 0}, None

def evaluate_action(frame, observation_ref, action):
    """Actively evaluate the registered model against an explicit real snapshot.

    The binding states what the caller supplied; it is not a safety certificate
    or an assertion that arbitrary local state equals the game state.
    """
    global _rollout_call_depth
    outer = _rollout_call_depth == 0
    _rollout_call_depth += 1
    try:
        ctx = current()
        if observation_ref != ctx['observation_ref'] or frame != _read('frame', [observation_ref['sequence']]):
            raise ValueError('candidate snapshot does not match current public observation')
        boundary = _rollout_boundary(ctx)
        assessment, result = _evaluate_registered(frame, observation_ref, action, boundary)
        frame_hash = 'sha256:' + _rollout_hashlib.sha256(_json.dumps(frame,allow_nan=False,
            ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if outer:
            _remember_rollout_call('evaluate_action', observation_ref, [[action]], result or assessment,
                                  _model_registration(), frame_hash)
        return result if result is not None else assessment
    except Exception:
        if outer:
            _remember_rollout_call('evaluate_action', observation_ref, [[action]],
                                  {'status':'failed','risk':'unassessed','reason':'candidate_evaluation_failed'})
        raise
    finally:
        _rollout_call_depth -= 1

def _drain_rollout_calls():
    calls = list(_rollout_calls)
    _rollout_calls.clear()
    return {'calls': calls, 'registration': _model_registration()}

def _host_evaluate_action(frame, reference, action, boundary):
    global _last_auto_rollout_result, _rollout_call_depth
    _rollout_call_depth += 1
    try:
        # Model diagnostics cannot replace the structured host assessment.
        with _rollout_contextlib.redirect_stdout(_rollout_io.StringIO()), _rollout_contextlib.redirect_stderr(_rollout_io.StringIO()):
            assessment, result = _evaluate_registered(frame, reference, action, boundary)
    finally:
        _rollout_call_depth -= 1
    _last_auto_rollout_result = result
    packed = None
    if result is not None:
        try:
            packed = _rollout_base64.b64encode(_rollout_zlib.compress(
                _json.dumps(result, allow_nan=False, separators=(',', ':')).encode())).decode()
        except Exception:
            assessment['evidence_status'] = 'result_artifact_unavailable'
    return {'assessment': assessment, 'registration': _model_registration(),
            'result_zlib_base64': packed}

def last_auto_rollout():
    """Read the last raw host model result in this kernel; not a live game call."""
    return _p7_rollout_copy(_last_auto_rollout_result)

def _invalidate_rollout_model():
    global _registered_rollout_model
    _registered_rollout_model = None
'''


class RolloutRuntime:
    """Sync solver callback into the runtime's admitted asynchronous kernel."""

    def __init__(self, owner, root: Path):
        self.owner = owner
        self.root = root / 'rollout-evidence'
        self.root.mkdir(parents=True, exist_ok=True)
        self.loop = None
        self.signal = None
        self.actor_calls = []
        self.last_actor_cell_id = None
        self.registration = None
        self.actor_cell_count = 0
        self.auto_cell_count = 0
        self.auto_attempts = 0
        self.auto_evaluated = 0
        self.actor_helper_calls = 0
        self.telemetry_failures = 0
        self._record_lock = threading.Lock()

    def _append(self, value):
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(',', ':')) + '\n'
        with self._record_lock:
            with (self.root / 'calls.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(encoded)

    async def _cell(self, code, signal, prefix):
        call_id = prefix + uuid.uuid4().hex
        result = await self.owner.kernel.execute(call_id, code, signal)
        if prefix == 'p7-auto-':
            self.auto_cell_count += 1
        if result.status != 'ok':
            raise ValueError('model computation unavailable')
        envelope = json.loads(result.content[0]['text'])
        if envelope.get('stdout_truncated'):
            raise ValueError('model computation truncated')
        value = json.loads(envelope['stdout'])
        history = self.owner.kernel.cell_history(start=max(0, self.owner.kernel.cell_history()['total'] - 1), limit=1)
        return value, history['items'][0]['cell_id']

    def revision(self, registration):
        if registration is None:
            return None
        return {'generation': str(self.owner.kernel.generation),
                'registration_id': registration['registration_id'],
                'last_actor_cell_id': self.last_actor_cell_id}

    async def collect_actor_calls(self, signal, actor_cell_id):
        self.actor_cell_count += 1
        self.last_actor_cell_id = actor_cell_id
        value, _ = await self._cell("import p7_research as _p7_r\nimport json as _p7_j\nprint(_p7_j.dumps(_p7_r._drain_rollout_calls(),allow_nan=False))", signal, 'p7-drain-')
        self.registration = value['registration']
        for item in value['calls']:
            from .score import digest
            current = self.owner.solver.current_context()
            binding_verified = (item['operation'] == 'evaluate_action'
                and item.get('observation_ref') == current['observation_ref']
                and item.get('frame_sha256') == digest(current['observation']['frame'][-1]))
            record = {**item, 'actor_cell_id': actor_cell_id,
                      'binding_verified': binding_verified,
                      'model_revision': self.revision(item['registration'])}
            self.actor_helper_calls += 1
            self.actor_calls.append(record)
            self.actor_calls = self.actor_calls[-128:]
            self._append(record)

    async def _evaluate(self, observation, reference, action):
        from .research_runtime import _ResearchSignal
        owner = self.owner
        combined = _ResearchSignal(owner, self.signal)
        if combined.cancelled or not owner.control.enter('cell'):
            return {'status': 'not_evaluated', 'risk': 'unassessed', 'reason': 'research_stopped', 'ticks': 0}
        try:
            boundary = {'run_id': reference['run_id'], 'attempt_id': reference['attempt_id'],
                        'level': reference['level'], 'reset_sequence': owner.solver._notes_boundary(reference)['reset_sequence']}
            payload = json.dumps([observation['frame'][-1], reference, action, boundary], allow_nan=False, separators=(',', ':')).encode()
            packed_input = base64.b64encode(zlib.compress(payload)).decode()
            code = "import p7_research as _p7_r\nimport json as _p7_j\nimport zlib as _p7_z\nimport base64 as _p7_b\nprint(_p7_j.dumps(_p7_r._host_evaluate_action(*_p7_j.loads(_p7_z.decompress(_p7_b.b64decode(" + repr(packed_input) + ")))),allow_nan=False))"
            value, cell_id = await self._cell(code, combined, 'p7-auto-')
            self.registration = value['registration']
            result = value['assessment']
            result.update(model_revision=self.revision(self.registration), cell_id=cell_id)
            packed = value.get('result_zlib_base64')
            if packed is not None:
                try:
                    raw = base64.b64decode(packed, validate=True)
                    artifact_id = 'sha256:' + hashlib.sha256(raw).hexdigest()
                    (self.root / (artifact_id[7:] + '.json.zlib')).write_bytes(raw)
                    result['result_artifact_id'] = artifact_id
                except Exception:
                    result['evidence_status'] = 'result_artifact_unavailable'
            return result
        finally:
            owner.control.leave('cell')
            owner.poll()

    def evaluate(self, observation, reference, action):
        started = monotonic()
        self.auto_attempts += 1
        result = {'status': 'not_evaluated', 'risk': 'unassessed', 'reason': 'kernel_bridge_unavailable', 'ticks': 0}
        if action['name'] == 'RESET':
            result['reason'] = 'reset_boundary'
        elif self.loop is not None and self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._evaluate(observation, reference, action), self.loop)
            # Kernel owns the real finite computation deadline. Polling here
            # permits native cancellation without introducing a second timeout.
            while True:
                try:
                    result = future.result(timeout=0.05)
                    break
                except FutureTimeout:
                    continue
                except Exception:
                    result['reason'] = 'model_evaluation_failed'
                    break
        if result['status'] == 'evaluated':
            self.auto_evaluated += 1
        revision = result.get('model_revision')
        if self.owner._closed or (self.signal is not None and self.signal.cancelled):
            result['hard_stop'] = 'cancelled'
        matching = [item for item in self.actor_calls
                    if item.get('binding_verified') and revision is not None
                    and item.get('observation_ref') == reference and item.get('model_revision') == revision
                    and [action] in item.get('candidate_actions', [])]
        result.update(origin='host_auto', observation_ref=reference, action=action,
                      matched_actor_calls=[item['call_sequence'] for item in matching],
                      elapsed_ms=round((monotonic() - started) * 1000, 3))
        try:
            self._append(result)
        except Exception:
            self.telemetry_failures += 1
            result['evidence_status'] = 'call_record_unavailable'
        return result

    def snapshot(self):
        return {'auto_attempts': self.auto_attempts, 'auto_evaluated': self.auto_evaluated,
                'auto_kernel_cells': self.auto_cell_count, 'actor_kernel_cells': self.actor_cell_count,
                'actor_helper_calls': self.actor_helper_calls, 'telemetry_failures': self.telemetry_failures}

    async def invalidate(self, signal):
        self.registration = None
        self.actor_calls.clear()
        if not self.owner.kernel.status()['lost']:
            await self._cell("import p7_research as _p7_r\n_p7_r._invalidate_rollout_model()\nprint('{}')", signal, 'p7-invalidate-')

    def telemetry_failed(self):
        self.telemetry_failures += 1
        self.actor_calls.clear()
        try:
            self._append({'origin': 'actor', 'status': 'telemetry_unavailable',
                          'reason': 'helper_call_evidence_unavailable',
                          'actor_cell_id': self.last_actor_cell_id})
        except Exception:
            pass  # The counter remains visible even if its archive is unwritable.
