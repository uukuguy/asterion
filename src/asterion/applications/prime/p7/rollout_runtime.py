"""P7-only registered models and evidence over the existing Prime kernel."""

from __future__ import annotations

import asyncio
import base64
from concurrent.futures import TimeoutError as FutureTimeout
import hashlib
import json
from pathlib import Path
import re
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
_rollout_pending_traces = {}
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
                          max_ticks_per_action=128, model_id='local', supported_actions=None):
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
    if supported_actions is not None:
        if (type(supported_actions) not in (list, tuple)
                or any(type(v) is not str or v not in [f'ACTION{i}' for i in range(1,8)]+['RESET'] for v in supported_actions)):
            raise ValueError('model action coverage invalid')
        supported_actions = sorted(set(supported_actions))
    boundary = _rollout_boundary(current())
    _rollout_registration_sequence += 1
    _registered_rollout_model = {'from_frame': from_frame, 'transition': transition,
        'settled': settled, 'terminal': terminal, 'risk_check': risk_check,
        'collision': collision, 'max_ticks_per_action': max_ticks_per_action,
        'supported_actions': supported_actions,
        'model_id': model_id, 'registration_id': _rollout_registration_sequence,
        'boundary': boundary}
    return {'status': 'registered', 'model_id': model_id,
            'registration_id': _rollout_registration_sequence, 'boundary': boundary,
            'supported_actions': supported_actions}

def _model_registration():
    model = _registered_rollout_model
    return None if model is None else {k: model[k] for k in ('model_id', 'registration_id', 'boundary', 'supported_actions')}

def _rollout_trace_summary(value, parent=None):
    if type(value) is list:
        return [_rollout_trace_summary(v) for v in value]
    if type(value) is dict:
        # Risk evidence and scalar expectations are conclusions, not trajectory
        # storage. Full model state appears only through the trace reference.
        result = {k: (_p7_rollout_copy(v) if k == 'risk' else _rollout_trace_summary(v,k))
                  for k,v in value.items()
                  if k not in ('states', 'initial_state') and not (k == 'state' and parent != 'expect')}
        risk = value.get('risk')
        if risk == 'unassessed' or (type(risk) is dict and risk.get('status') == 'unassessed'):
            result['assessment_notice'] = 'risk_assessment_incomplete'
        return result
    return value

def _actor_rollout_result(result, full):
    summary = _rollout_trace_summary(result)
    try:
        packed = _rollout_zlib.compress(_json.dumps(result,allow_nan=False,
            ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        reference = 'sha256:' + _rollout_hashlib.sha256(packed).hexdigest()
        _rollout_pending_traces[reference] = packed
        summary['full_trace_ref'] = reference
        summary['evidence_status'] = 'kernel_retained_pending_archive'
    except Exception:
        summary['full_trace_ref'] = None
        summary['evidence_status'] = 'result_artifact_unavailable'
    return (result if full else summary), summary

def _rollout_trace_page(value, reference, section, start, limit):
    if (type(section) is not list or len(section)>16
            or any(type(v) not in (str,int) or (type(v) is int and v<0) for v in section)
            or type(start) is not int or start<0 or type(limit) is not int or not 1<=limit<=32):
        raise ValueError('trace page invalid')
    for key in section:
        if type(value) is dict and type(key) is str:
            value = value[key]
        elif type(value) is list and type(key) is int:
            value = value[key]
        else:
            raise ValueError('trace section invalid')
    items = value if type(value) is list else [{'key':k,'value':v} for k,v in value.items()] if type(value) is dict else [value]
    end = min(start+limit,len(items))
    return {'full_trace_ref':reference,'section':section,'start':start,'total':len(items),
            'items':_p7_rollout_copy(items[start:end]),'next_start':end if end<len(items) else None,
            'raw_values':True}

def read_rollout_trace(full_trace_ref, *, section=None, start=0, limit=8):
    """Read selected raw trace values, including original pixels for computation.

    section is a list of mapping keys/list indices; list values page by item.
    This does not execute a game, rerun callbacks, or omit pixel values.
    """
    section = [] if section is None else section
    packed = _rollout_pending_traces.get(full_trace_ref)
    if packed is not None:
        return _rollout_trace_page(_json.loads(_rollout_zlib.decompress(packed)),full_trace_ref,section,start,limit)
    return _read('rollout_trace',[full_trace_ref,section,start,limit])

def _rollout_compact(result):
    risk = result.get('risk', {})
    if type(risk) is not dict:
        risk = {'status': risk}
    return {'status': result.get('status', 'evaluated'), 'risk': risk.get('status', 'unassessed'),
            'reason': result.get('reason', 'model-relative'), 'outcome': result.get('outcome'),
            'ticks': result.get('ticks', 0), 'coverage': risk.get('coverage'),
            'findings': risk.get('findings', []), 'execution_authority': 'none',
            'claims': 'model-relative'}

def _remember_rollout_call(operation, reference, candidates, result, registration=None, frame_sha256=None, trace_ref=None):
    global _rollout_call_sequence
    _rollout_call_sequence += 1
    _rollout_calls.append({'operation': operation, 'origin': 'actor',
        'call_sequence': _rollout_call_sequence,
        'observation_ref': _p7_rollout_copy(reference),
        'candidate_actions': _p7_rollout_copy(candidates),
        'registration': registration, 'frame_sha256': frame_sha256,
        'full_trace_ref': trace_ref,
        'result': _rollout_compact(result)})

def _actor_rollout_call(operation, function, args, kwargs, candidates):
    global _rollout_call_depth
    reference = kwargs.pop('observation_ref', None)
    full = kwargs.pop('full', False)
    if type(full) is not bool:
        raise ValueError('full requires a boolean')
    outer = _rollout_call_depth == 0
    # Arbitrary raw-helper states do not prove the registered initializer was
    # used. They remain real calls, but cannot cover a host candidate.
    registration = None
    _rollout_call_depth += 1
    try:
        result = function(*args, **kwargs)
        if outer:
            returned, summary = _actor_rollout_result(result, full)
            _remember_rollout_call(operation, reference, candidates, result, registration,
                                  trace_ref=summary['full_trace_ref'])
            return returned
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
            risk_check=model['risk_check'], supported_actions=model['supported_actions'])
        return _rollout_compact(result), result
    except Exception:
        return {'status': 'not_evaluated', 'risk': 'unassessed', 'reason': 'model_callback_failed', 'ticks': 0}, None

def evaluate_action(frame, observation_ref, action, *, full=False):
    """Actively evaluate the registered model against an explicit real snapshot.

    The binding states what the caller supplied; it is not a safety certificate
    or an assertion that arbitrary local state equals the game state.
    """
    global _rollout_call_depth
    outer = _rollout_call_depth == 0
    _rollout_call_depth += 1
    try:
        if type(full) is not bool:
            raise ValueError('full requires a boolean')
        ctx = current()
        if observation_ref != ctx['observation_ref'] or frame != _read('frame', [observation_ref['sequence']]):
            raise ValueError('candidate snapshot does not match current public observation')
        boundary = _rollout_boundary(ctx)
        assessment, result = _evaluate_registered(frame, observation_ref, action, boundary)
        frame_hash = 'sha256:' + _rollout_hashlib.sha256(_json.dumps(frame,allow_nan=False,
            ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if outer:
            returned, summary = _actor_rollout_result(result or assessment, full)
            _remember_rollout_call('evaluate_action', observation_ref, [[action]], result or assessment,
                                  _model_registration(), frame_hash, summary['full_trace_ref'])
            return returned
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
    traces = {ref:_rollout_base64.b64encode(packed).decode() for ref,packed in _rollout_pending_traces.items()}
    _rollout_pending_traces.clear()
    return {'calls': calls, 'registration': _model_registration(), 'traces':traces}

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
        self.counterexample_revisions = set()
        self.observed_death_cases = {}
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
        unavailable = set()
        for reference, encoded in value.get('traces', {}).items():
            try:
                packed = base64.b64decode(encoded, validate=True)
                if reference != 'sha256:' + hashlib.sha256(packed).hexdigest():
                    raise ValueError('trace identity unavailable')
                (self.root / (reference[7:] + '.json.zlib')).write_bytes(packed)
            except Exception:
                self.telemetry_failures += 1
                unavailable.add(reference)
        for item in value['calls']:
            from .score import digest
            current = self.owner.solver.current_context()
            binding_verified = (item['operation'] == 'evaluate_action'
                and item.get('observation_ref') == current['observation_ref']
                and item.get('frame_sha256') == digest(current['observation']['frame'][-1]))
            record = {**item, 'actor_cell_id': actor_cell_id,
                      'binding_verified': binding_verified,
                      'model_revision': self.revision(item['registration'])}
            if item.get('full_trace_ref') in unavailable:
                record['evidence_status'] = 'result_artifact_unavailable'
            self.actor_helper_calls += 1
            self.actor_calls.append(record)
            self.actor_calls = self.actor_calls[-128:]
            self._append(record)

    def read_trace(self, reference, section, start, limit):
        """Selected raw JSON pages from host-retained current-run evidence."""
        if (type(reference) is not str or re.fullmatch(r'sha256:[0-9a-f]{64}', reference) is None
                or type(section) is not list or len(section) > 16
                or any(type(v) not in (str, int) or (type(v) is int and v < 0) for v in section)
                or type(start) is not int or start < 0 or type(limit) is not int or not 1 <= limit <= 32):
            raise ValueError('trace page invalid')
        packed = (self.root / (reference[7:] + '.json.zlib')).read_bytes()
        if reference != 'sha256:' + hashlib.sha256(packed).hexdigest():
            raise ValueError('trace identity unavailable')
        value = json.loads(zlib.decompress(packed))
        for key in section:
            if type(value) is dict and type(key) is str:
                value = value[key]
            elif type(value) is list and type(key) is int:
                value = value[key]
            else:
                raise ValueError('trace section invalid')
        items = value if type(value) is list else [{'key': k, 'value': v} for k, v in value.items()] if type(value) is dict else [value]
        end = min(start + limit, len(items))
        return {'full_trace_ref': reference, 'section': section, 'start': start, 'total': len(items),
                'items': items[start:end], 'next_start': end if end < len(items) else None, 'raw_values': True}

    def model_case_status(self, revision):
        key = self._registration_key(revision)
        return 'counterexample_observed' if key in self.counterexample_revisions else 'not_checked'

    @staticmethod
    def _registration_key(revision):
        return None if revision is None else (revision['generation'], revision['registration_id'])

    def record_feedback(self, assessment, before_ref, after_ref, action, actual_state):
        """Record an observed death against its exact pre-action model result."""
        if actual_state != 'GAME_OVER':
            return None
        assessment = assessment or {}
        risk = assessment.get('risk', 'unassessed')
        if type(risk) is dict:
            risk = risk.get('status', 'unassessed')
        outcome = assessment.get('outcome')
        mismatch = assessment.get('status') == 'evaluated' and outcome in ('settled', 'goal', 'collision')
        kind = 'model_mismatch' if mismatch else 'model_risk_observed' if outcome == 'dead' else 'death_not_assessed'
        revision = assessment.get('model_revision')
        record = {'origin': 'host_feedback', 'type': kind,
                  'before_observation_ref': before_ref, 'after_observation_ref': after_ref,
                  'action': action, 'actual_state': actual_state, 'predicted_risk': risk,
                  'predicted_outcome': assessment.get('outcome'), 'model_revision': revision,
                  'full_trace_ref': assessment.get('result_artifact_id'),
                  'death_case_sequence': after_ref.get('sequence'),
                  'frame_sha256': assessment.get('frame_sha256'), 'level': before_ref.get('level'),
                  'claims': 'observed-case-only', 'execution_authority': 'none'}
        if record['frame_sha256'] is not None and record['level'] is not None:
            key = (record['frame_sha256'], record['level'], json.dumps(action, sort_keys=True, separators=(',', ':')))
            self.observed_death_cases[key] = json.loads(json.dumps(record))
        if mismatch and revision is not None:
            self.counterexample_revisions.add(self._registration_key(revision))
        try:
            self._append(record)
        except Exception:
            self.telemetry_failures += 1
            record['evidence_status'] = 'feedback_record_unavailable'
        return record

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
            result['model_case_status'] = self.model_case_status(result['model_revision'])
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
        from .score import digest
        result['frame_sha256'] = digest(observation['frame'][-1])
        key = (result['frame_sha256'], reference.get('level'), json.dumps(action, sort_keys=True, separators=(',', ':')))
        observed_death = self.observed_death_cases.get(key)
        if observed_death is not None and action['name'] != 'RESET':
            result['model_risk'] = result['risk']
            if result['risk'] != 'predicted_death':
                result['risk'] = 'conditional_fatal'
            result.setdefault('findings', []).append({
                'id': 'current-run-death-case', 'type': 'conditional_fatal',
                'condition': 'Same public pixels, level and action as an observed death; hidden state may differ.',
                'evidence': {'source': 'current_run_death_case',
                    'frame_sha256': result['frame_sha256'],
                    'before_observation_ref': observed_death['before_observation_ref'],
                    'after_observation_ref': observed_death['after_observation_ref']}})
            result['reason'] = 'current_run_death_case'
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
