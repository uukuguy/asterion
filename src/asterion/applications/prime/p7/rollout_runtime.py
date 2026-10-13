"""P7-only registered models and evidence over the existing Prime kernel."""

from __future__ import annotations

import asyncio
import base64
from contextlib import nullcontext
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
import builtins as _rollout_builtins
import dis as _rollout_dis
import types as _rollout_types
_registered_rollout_model = None
_rollout_scope_extractors = {}
_rollout_scope_builtins = {name:getattr(_rollout_builtins,name) for name in
    ('range','len','min','max','enumerate','sorted','zip','sum','abs','hasattr','round',
     'all','any','int','float','bool','str','list','dict','tuple','set')}
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

def _rollout_state_digest(state):
    return 'sha256:' + _rollout_hashlib.sha256(_json.dumps(_p7_rollout_copy(state),
        allow_nan=False,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def _rollout_scope_fingerprint(function, seen=()):
    # A deliberately narrow dependency contract, not a sandbox or general
    # purity proof. Unsupported dependencies leave applicability unavailable.
    if type(function) is not _rollout_types.FunctionType or id(function) in seen or len(seen)>=8:
        raise ValueError('scope dependency unsupported')
    seen = (*seen,id(function))
    names = set()
    def inspect_code(code):
        for instruction in _rollout_dis.get_instructions(code):
            if instruction.opname in ('IMPORT_NAME','STORE_GLOBAL','DELETE_GLOBAL'):
                raise ValueError('scope dependency unsupported')
            # Comprehensions may capture this call's local cells (e.g. frame
            # and loop coordinates). Only writes to external closure cells
            # change retained dependencies beyond the copied inputs.
            if instruction.opname in ('STORE_DEREF','DELETE_DEREF') and instruction.argval in code.co_freevars:
                raise ValueError('scope dependency unsupported')
            if instruction.opname == 'LOAD_GLOBAL':
                names.add(instruction.argval)
        for constant in code.co_consts:
            if type(constant) is _rollout_types.CodeType:
                inspect_code(constant)
    inspect_code(function.__code__)
    def code_value(value):
        if type(value) is _rollout_types.CodeType:
            return {'code':value.co_code.hex(),'exceptiontable':value.co_exceptiontable.hex(),
                'names':list(value.co_names),'varnames':list(value.co_varnames),
                'freevars':list(value.co_freevars),'cellvars':list(value.co_cellvars),
                'argcount':value.co_argcount,'posonly':value.co_posonlyargcount,
                'kwonly':value.co_kwonlyargcount,'flags':value.co_flags,
                'constants':[code_value(v) for v in value.co_consts]}
        if type(value) is tuple:
            return {'tuple':[code_value(v) for v in value]}
        if type(value) is frozenset:
            items = [code_value(v) for v in value]
            return {'frozenset':sorted(items,key=lambda v:_json.dumps(v,sort_keys=True))}
        if type(value) is slice:
            return {'slice':[code_value(value.start),code_value(value.stop),code_value(value.step)]}
        if type(value) is bytes:
            return {'bytes':value.hex()}
        if value is Ellipsis:
            return {'ellipsis':True}
        return {'scalar':_p7_rollout_copy(value)}
    def dependency(value):
        if type(value) is _rollout_types.FunctionType:
            return {'function':_rollout_scope_fingerprint(value,seen)}
        return {'json':_p7_rollout_copy(value)}
    dependencies = {}
    for name in sorted(names):
        if name in function.__globals__:
            dependencies[name] = dependency(function.__globals__[name])
        elif name not in _rollout_scope_builtins or function.__builtins__.get(name) is not _rollout_scope_builtins[name]:
            raise ValueError('scope dependency unsupported')
    # Describe code structurally: marshal reference flags can depend on object
    # retention, and old marshal versions cannot encode Python 3.14 slices.
    payload = {'code':code_value(function.__code__),
        'defaults':dependency(list(function.__defaults__ or ())),
        'kwdefaults':dependency(function.__kwdefaults__),
        'closure':[dependency(cell.cell_contents) for cell in function.__closure__ or ()],
        'globals':dependencies}
    return _rollout_state_digest(payload)

def _rollout_extract_retained_scope(extractor_id, frame, reference):
    retained = _rollout_scope_extractors.get(extractor_id)
    try:
        if retained is None or retained['fingerprint'] is None:
            raise ValueError('scope unavailable')
        function = retained['function']
        if _rollout_scope_fingerprint(function) != retained['fingerprint']:
            raise ValueError('scope dependencies changed')
        state = function(_p7_rollout_copy(frame),_p7_rollout_copy(reference))
        digest = _rollout_state_digest(state)
        if _rollout_scope_fingerprint(function) != retained['fingerprint']:
            raise ValueError('scope dependencies changed')
        return {'status':'available','initial_state_sha256':digest}
    except Exception:
        return {'status':'unavailable'}

def _rollout_compact(result):
    risk = result.get('risk', {})
    if type(risk) is not dict:
        risk = {'status': risk}
    return {'status': result.get('status', 'evaluated'), 'risk': risk.get('status', 'unassessed'),
            'reason': result.get('reason', 'model-relative'), 'outcome': result.get('outcome'),
            'ticks': result.get('ticks', 0), 'coverage': risk.get('coverage'),
            'evaluated_actions': result.get('evaluated_actions', 0),
            'findings': risk.get('findings', []), 'execution_authority': 'none',
            'claims': 'model-relative', 'initial_state_sha256':result.get('initial_state_sha256'),
            'scope_extractor_id':result.get('scope_extractor_id')}

def _remember_rollout_call(operation, reference, candidates, result, registration=None, frame_sha256=None, trace_ref=None):
    global _rollout_call_sequence
    _rollout_call_sequence += 1
    _rollout_calls.append({'operation': operation, 'origin': 'actor',
        'call_sequence': _rollout_call_sequence,
        'observation_ref': _p7_rollout_copy(reference),
        'candidate_actions': _p7_rollout_copy(candidates),
        'registration': registration, 'frame_sha256': frame_sha256,
        'initial_state_sha256':result.get('initial_state_sha256'),
        'scope_extractor_id':result.get('scope_extractor_id'),
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
        return _rollout_unavailable('model_missing','model_unavailable'), None
    if model['boundary'] != boundary:
        _registered_rollout_model = None
        return _rollout_unavailable('model_boundary_invalidated','model_unavailable'), None
    try:
        try:
            fingerprint = _rollout_scope_fingerprint(model['from_frame'])
        except Exception:
            fingerprint = None
        initial = model['from_frame'](_p7_rollout_copy(frame), _p7_rollout_copy(reference))
        initial_digest = _rollout_state_digest(initial)
        if fingerprint is not None:
            try:
                if _rollout_scope_fingerprint(model['from_frame']) != fingerprint:
                    fingerprint = None
            except Exception:
                fingerprint = None
        result = _raw_rollout(initial, [action], transition=model['transition'],
            settled=model['settled'], terminal=model['terminal'],
            collision=model['collision'], max_ticks_per_action=model['max_ticks_per_action'],
            risk_check=model['risk_check'], supported_actions=model['supported_actions'])
        result['initial_state_sha256'] = initial_digest
        if result['risk']['status'] in ('predicted_death','conditional_fatal'):
            extractor_id = str(model['registration_id']) + ':' + (fingerprint or 'unavailable')
            if extractor_id not in _rollout_scope_extractors:
                _rollout_scope_extractors[extractor_id] = {'function':model['from_frame'],'fingerprint':fingerprint}
            result['scope_extractor_id'] = extractor_id
        return _rollout_compact(result), result
    except Exception:
        return _rollout_unavailable('model_callback_failed','computation_failure'), None

def _rollout_unavailable(reason, kind):
    risk = _p7_rollout_risk_new(None)
    _p7_rollout_gap(risk,kind,0,reason)
    return {'status':'not_evaluated','risk':'unassessed','reason':reason,'ticks':0,
            'coverage':risk['coverage'],'execution_authority':'none','claims':'model-relative'}

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

def _host_evaluate_action(frame, reference, action, boundary, scope_extractor_ids=None):
    global _last_auto_rollout_result, _rollout_call_depth
    _rollout_call_depth += 1
    try:
        # Model diagnostics cannot replace the structured host assessment.
        with _rollout_contextlib.redirect_stdout(_rollout_io.StringIO()), _rollout_contextlib.redirect_stderr(_rollout_io.StringIO()):
            assessment, result = _evaluate_registered(frame, reference, action, boundary)
            scopes = {key:_rollout_extract_retained_scope(key,frame,reference)
                      for key in scope_extractor_ids or []}
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
            'retained_scope_assessments':scopes,
            'result_zlib_base64': packed}

def last_auto_rollout():
    """Read the last raw host model result in this kernel; not a live game call."""
    return _p7_rollout_copy(_last_auto_rollout_result)

def _host_backtest_action(frame, reference, action, boundary):
    global _last_auto_rollout_result
    saved = _last_auto_rollout_result
    try:
        return _host_evaluate_action(frame,reference,action,boundary)
    finally:
        _last_auto_rollout_result = saved

def _invalidate_rollout_model():
    global _registered_rollout_model
    _registered_rollout_model = None
'''


def _unavailable_assessment(reason, kind='computation_failure', phase='input'):
    return {'status': 'not_evaluated', 'risk': 'unassessed', 'reason': reason, 'ticks': 0,
            'coverage': {'checker_supplied': False, 'evaluated_ticks': 0, 'unassessed_ticks': 0,
                         'errors': [], 'partial': True, 'action_coverage': 'undeclared',
                         'gaps': [{'kind': kind, 'phase': phase, 'action_index': None,
                                   'tick': 0, 'reason': reason}], 'gaps_omitted': 0},
            'execution_authority': 'none', 'claims': 'model-relative'}


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
        # Append-only host witnesses survive registration, RESET and kernel
        # replacement. Matching is exact model-state/action or public-frame;
        # neither asserts generalized dangerous-region or hidden-state rules.
        self.retained_fatal_risks = []
        self._retained_fatal_keys = set()
        self._record_lock = threading.Lock()
        self._cases = {}
        self._case_version = 0
        self._backtest_cache_key = None
        self._backtest_results = {}
        self._restore_cases()

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
            if binding_verified:
                for candidate in item.get('candidate_actions', []):
                    if len(candidate) == 1:
                        self._retain_fatal(record['result'], record['observation_ref'], candidate[0],
                                           record['frame_sha256'], record['model_revision'],
                                           record.get('full_trace_ref'), 'actor')
            self._append(record)
        await self._ensure_backtest(signal)

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
        if key in self.counterexample_revisions:
            return 'counterexample_observed'
        summary = self.snapshot_backtest()
        if summary['case_count'] and summary['model_revision'] == revision:
            return summary['status']
        return 'not_checked'

    def _restore_cases(self):
        path = self.root / 'calls.jsonl'
        if not path.is_file():
            return
        try:
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                        if (type(record) is dict and record.get('origin') == 'host_feedback'
                                and record.get('type') in ('model_mismatch', 'model_risk_observed',
                                                           'death_not_assessed', 'plan_expectation_mismatch')):
                            self._remember_case(record)
                    except (ValueError, TypeError, KeyError):
                        self.telemetry_failures += 1
        except OSError:
            self.telemetry_failures += 1

    def _remember_case(self, record):
        from .score import digest
        record = json.loads(json.dumps(record, allow_nan=False))
        before, after, action = (record[key] for key in ('before_observation_ref', 'after_observation_ref', 'action'))
        if (type(before) is not dict or type(after) is not dict or type(action) is not dict
                or set(action) != {'name', 'data'} or type(action['data']) is not dict
                or action['name'] not in [f'ACTION{i}' for i in range(1, 8)]):
            raise ValueError('case identity unavailable')
        case_id = digest({key: record.get(key) for key in (
            'type', 'before_observation_ref', 'after_observation_ref', 'action',
            'actual_state', 'expected', 'differences', 'model_revision')})
        record['case_id'] = case_id
        if case_id not in self._cases:
            self._cases[case_id] = record
            self._case_version += 1
        if record['type'] == 'model_mismatch' and record.get('model_revision') is not None:
            self.counterexample_revisions.add(self._registration_key(record['model_revision']))
        if record.get('actual_state') == 'GAME_OVER' and record.get('frame_sha256') is not None and record.get('level') is not None:
            key = (before.get('run_id'), record['frame_sha256'], record['level'], self._action_key(action))
            self.observed_death_cases[key] = record
        return record

    def _case_context(self):
        try:
            return self.owner.solver.current_context()
        except (AttributeError, ValueError):
            return {'observation_ref': {}}

    def _current_cases(self, context):
        reference = context['observation_ref']
        return [case for case in self._cases.values()
                if reference.get('run_id') is not None and reference.get('level') is not None
                and case['before_observation_ref'].get('run_id') == reference['run_id']
                and case['before_observation_ref'].get('level') == reference['level']]

    def _backtest_key(self, context):
        reference = context['observation_ref']
        return (self._action_key(self.revision(self.registration)), self._case_version,
                reference.get('run_id'), reference.get('level'))

    @staticmethod
    def _risk_assessment_incomplete(assessment):
        risk = assessment.get('risk', 'unassessed')
        coverage = assessment.get('coverage')
        if type(risk) is dict:
            coverage = risk.get('coverage', coverage)
            risk = risk.get('status', 'unassessed')
        return risk == 'unassessed' or (type(coverage) is dict and bool(
            coverage.get('partial') or coverage.get('unassessed_ticks') or coverage.get('errors')
        ))

    @staticmethod
    def _case_summary(case):
        return {key: case[key] for key in (
            'case_id', 'type', 'before_observation_ref', 'after_observation_ref', 'action',
            'actual_state', 'model_revision', 'expected', 'differences', 'full_trace_ref', 'claim_source', 'actual',
            'predicted_risk', 'predicted_outcome', 'coverage', 'findings',
        ) if key in case}

    def snapshot_backtest(self):
        context = self._case_context()
        cases = self._current_cases(context)
        current = self._backtest_cache_key == self._backtest_key(context)
        results = [{**self._case_summary(case), **(self._backtest_results[case['case_id']] if current else {
            'status': 'unavailable' if self.registration is None else 'unknown',
            'reason': 'model_missing' if self.registration is None else 'case_revision_not_rechecked',
        })} for case in cases]
        statuses = {result['status'] for result in results}
        status = next((value for value in ('contradicted', 'unavailable', 'unknown', 'not_comparable', 'matched')
                       if value in statuses), 'not_checked')
        return json.loads(json.dumps({
            'status': status, 'case_count': len(results),
            'unresolved_count': sum(result['status'] != 'matched' for result in results),
            'cases': results[:32], 'omitted_cases': max(0, len(results) - 32),
            'model_revision': self.revision(self.registration), 'case_version': self._case_version,
            'execution_authority': 'none', 'claims': 'current-run-cases-only',
        }, allow_nan=False))

    def _case_observation(self, reference):
        try:
            lock = getattr(getattr(self.owner, '_broker', None), '_evidence_lock', nullcontext())
            with lock:
                observation, checked = self.owner._committed_observation(reference['sequence'])
            if checked != reference:
                raise ValueError('case observation unavailable')
            frame = [list(row) for row in observation.frame[-1]]
            return json.loads(json.dumps({'frame': frame, 'state': observation.state,
                                         'levels_completed': observation.levels_completed}, allow_nan=False))
        except (AttributeError, KeyError, ValueError, TypeError, IndexError):
            return None

    async def _ensure_backtest(self, signal):
        from .research_runtime import _ResearchSignal
        from .score import digest
        context = self._case_context()
        key = self._backtest_key(context)
        if key == self._backtest_cache_key:
            return
        revision = self.revision(self.registration)
        boundary = self.registration.get('boundary') if self.registration else None
        reference = context['observation_ref']
        current_boundary = {key: reference.get(key) for key in ('run_id', 'attempt_id', 'level')}
        current_boundary['reset_sequence'] = context.get('notes_boundary', {}).get('reset_sequence', 0)
        results = {}
        for case in self._current_cases(context):
            checked = {'status': 'unavailable', 'reason': 'model_missing'}
            before = case.get('before_observation')
            if boundary is None or boundary != current_boundary:
                checked['reason'] = 'model_missing' if boundary is None else 'model_boundary_invalidated'
            elif type(before) is not dict or digest(before.get('frame')) != case.get('frame_sha256'):
                checked['reason'] = 'case_observation_unavailable'
            else:
                combined = _ResearchSignal(self.owner, signal)
                if combined.cancelled or not self.owner.control.enter('cell'):
                    checked['reason'] = 'research_stopped'
                else:
                    try:
                        payload = json.dumps([before['frame'], case['before_observation_ref'], case['action'], boundary],
                                             allow_nan=False, separators=(',', ':')).encode()
                        packed_input = base64.b64encode(zlib.compress(payload)).decode()
                        code = "import p7_research as _p7_r\nimport json as _p7_j\nimport zlib as _p7_z\nimport base64 as _p7_b\nprint(_p7_j.dumps(_p7_r._host_backtest_action(*_p7_j.loads(_p7_z.decompress(_p7_b.b64decode(" + repr(packed_input) + ")))),allow_nan=False))"
                        value, cell_id = await self._cell(code, combined, 'p7-backtest-')
                        assessment = value['assessment']
                        checked = {'status': 'unknown', 'reason': assessment.get('reason', 'model-relative'),
                                   'predicted_outcome': assessment.get('outcome'), 'cell_id': cell_id,
                                   'predicted_risk': assessment.get('risk', 'unassessed'),
                                   'coverage': assessment.get('coverage'),
                                   'findings': assessment.get('findings', [])}
                        if str(self.owner.kernel.generation) != revision['generation'] or combined.cancelled:
                            checked.update(status='unavailable', reason='model_evaluation_failed')
                        elif assessment.get('status') != 'evaluated':
                            checked['status'] = 'unavailable'
                        elif case['type'] == 'plan_expectation_mismatch':
                            checked.update(status='not_comparable', reason='plan_claim_has_no_model_projection')
                        elif assessment.get('evaluated_actions', 0) == 0 and assessment.get('outcome') in ('dead', 'goal'):
                            checked.update(status='unknown', reason='initial_terminal_no_transition')
                        elif self._risk_assessment_incomplete(assessment):
                            checked.update(status='unknown', reason='risk_assessment_incomplete')
                        elif assessment.get('outcome') == 'dead':
                            checked.update(status='matched', reason='observed_death_matched')
                        elif assessment.get('outcome') in ('settled', 'goal', 'collision'):
                            checked.update(status='contradicted', reason='observed_death_contradicted')
                        packed = value.get('result_zlib_base64')
                        if packed is not None:
                            raw = base64.b64decode(packed, validate=True)
                            artifact_id = 'sha256:' + hashlib.sha256(raw).hexdigest()
                            (self.root / (artifact_id[7:] + '.json.zlib')).write_bytes(raw)
                            checked['result_artifact_id'] = artifact_id
                    except Exception:
                        checked = {'status': 'unavailable', 'reason': 'model_evaluation_failed'}
                    finally:
                        self.owner.control.leave('cell')
                        self.owner.poll()
            results[case['case_id']] = checked
            try:
                self._append({'origin': 'host_backtest', **self._case_summary(case), **checked,
                              'rechecked_model_revision': revision, 'case_version': self._case_version,
                              'execution_authority': 'none', 'claims': 'current-run-cases-only'})
            except Exception:
                self.telemetry_failures += 1
        self._backtest_results = results
        self._backtest_cache_key = key

    @staticmethod
    def _registration_key(revision):
        return None if revision is None else (revision['generation'], revision['registration_id'])

    @staticmethod
    def _action_key(action):
        return json.dumps(action, allow_nan=False, sort_keys=True, separators=(',', ':'))

    def _retain_fatal(self, assessment, reference, action, frame_hash, revision, trace_ref, origin):
        if assessment.get('risk') not in ('predicted_death', 'conditional_fatal'):
            return
        identity = (self._registration_key(revision), reference.get('run_id'), reference.get('level'),
                    self._action_key(action), assessment.get('initial_state_sha256') or frame_hash,
                    assessment['risk'], self._action_key(assessment.get('findings', [])))
        if identity in self._retained_fatal_keys:
            return
        witness = {'origin': origin, 'risk': assessment['risk'],
                   'findings': assessment.get('findings', []), 'observation_ref': reference,
                   'action': action, 'model_revision': revision, 'full_trace_ref': trace_ref,
                   'initial_state_sha256': assessment.get('initial_state_sha256'),
                   'frame_sha256': frame_hash, 'scope_extractor_id': assessment.get('scope_extractor_id'),
                   'claims': 'retained-model-relative-finding', 'execution_authority': 'none'}
        self.retained_fatal_risks.append(json.loads(json.dumps(witness, allow_nan=False)))
        self._retained_fatal_keys.add(identity)

    def _candidate_witnesses(self, reference, action):
        # A run ID is part of the authority scope. Older unit-test references
        # without a run ID may still exercise observed deaths separately.
        return [w for w in self.retained_fatal_risks
                if w['observation_ref'].get('run_id') == reference.get('run_id')
                and w['observation_ref'].get('level') == reference.get('level')
                and self._action_key(w['action']) == self._action_key(action)]

    def _apply_retained_fatal(self, result, reference, action):
        matches, unavailable = [], []
        scopes = result.pop('_retained_scope_assessments', {})
        generation = str(self.owner.kernel.generation) if getattr(self.owner, 'kernel', None) is not None else None
        for witness in self._candidate_witnesses(reference, action):
            revision = witness.get('model_revision')
            scope = scopes.get(witness.get('scope_extractor_id'), {}) if revision and revision['generation'] == generation else {}
            if scope.get('status') == 'available':
                if scope.get('initial_state_sha256') != witness['initial_state_sha256']:
                    continue
                match = 'initial_state'
            elif witness['frame_sha256'] == result['frame_sha256']:
                # Pixels cannot establish equivalence of reference-dependent
                # or hidden state when the original extractor is unavailable.
                match = 'public_frame'
            else:
                unavailable.append(witness)
                continue
            matches.append({**witness, 'match': match})
        if matches:
            result['model_risk'] = result['risk']
            if any(w['risk'] == 'predicted_death' and w['match'] == 'initial_state' for w in matches):
                result['risk'] = 'predicted_death'
            elif result['risk'] != 'predicted_death':
                result['risk'] = 'conditional_fatal'
            # Preserve the original finding independently of the new model's
            # conclusion. Full state remains behind its original trace ref.
            result['retained_fatal_risks'] = matches
            result['reason'] = 'retained_fatal_risk'
        if unavailable and not matches and result['risk'] not in ('predicted_death', 'conditional_fatal'):
            result['hard_stop'] = 'risk_applicability_unavailable'
            result['reason'] = 'risk_applicability_unavailable'
            result['retained_fatal_risks'] = [{**w, 'match': 'unavailable'} for w in unavailable]

    def record_feedback(self, assessment, before_ref, after_ref, action, actual_state, *, step_feedback=None):
        """Keep observed deaths and actor plan claims as distinct current-run cases."""
        differences = step_feedback.get('differences', []) if type(step_feedback) is dict else []
        if actual_state != 'GAME_OVER' and not differences:
            return None
        assessment = assessment or {}
        risk = assessment.get('risk', 'unassessed')
        coverage, findings = assessment.get('coverage'), assessment.get('findings', [])
        if type(risk) is dict:
            coverage, findings = risk.get('coverage', coverage), risk.get('findings', findings)
            risk = risk.get('status', 'unassessed')
        outcome = assessment.get('outcome')
        mismatch = (assessment.get('status') == 'evaluated' and outcome in ('settled', 'goal', 'collision')
                    and not self._risk_assessment_incomplete(assessment))
        kind = (
            'plan_expectation_mismatch' if actual_state != 'GAME_OVER' else
            'model_mismatch' if mismatch else 'model_risk_observed' if outcome == 'dead' else 'death_not_assessed'
        )
        revision = assessment.get('model_revision')
        record = {'origin': 'host_feedback', 'type': kind,
                  'before_observation_ref': before_ref, 'after_observation_ref': after_ref,
                  'action': action, 'actual_state': actual_state, 'predicted_risk': risk,
                  'predicted_outcome': assessment.get('outcome'), 'model_revision': revision,
                  'coverage': coverage, 'findings': findings,
                  'full_trace_ref': assessment.get('result_artifact_id'),
                  'death_case_sequence': after_ref.get('sequence'),
                  'frame_sha256': assessment.get('frame_sha256'), 'level': before_ref.get('level'),
                  'claims': 'observed-case-only', 'execution_authority': 'none'}
        if actual_state != 'GAME_OVER':
            record.pop('death_case_sequence')
        before, after = self._case_observation(before_ref), self._case_observation(after_ref)
        if before is not None and record['frame_sha256'] is None:
            from .score import digest
            record['frame_sha256'] = digest(before['frame'])
        record.update(before_observation=before, after_observation=after)
        records = [record]
        if differences:
            claim = {**record, 'type': 'plan_expectation_mismatch',
                     'expected': step_feedback.get('expected'), 'differences': differences,
                     'actual': step_feedback.get('actual'), 'claim_source': 'actor_plan_expectation'}
            claim.pop('death_case_sequence', None)
            if actual_state == 'GAME_OVER':
                records.append(claim)
            else:
                records = [claim]
        persisted = []
        for item in records:
            case = self._remember_case(item)
            try:
                self._append(case)
            except Exception:
                self.telemetry_failures += 1
                case['evidence_status'] = 'feedback_record_unavailable'
            persisted.append(case)
        returned = {key: value for key, value in persisted[0].items()
                    if key not in ('before_observation', 'after_observation')}
        if len(persisted) > 1:
            returned['related_plan_claim_case_id'] = persisted[1]['case_id']
        return returned

    async def _evaluate(self, observation, reference, action):
        from .research_runtime import _ResearchSignal
        owner = self.owner
        combined = _ResearchSignal(owner, self.signal)
        await self._ensure_backtest(combined)
        if combined.cancelled or not owner.control.enter('cell'):
            result = _unavailable_assessment('research_stopped', 'model_unavailable')
            result['backtest'] = self.snapshot_backtest()
            return result
        try:
            boundary = {'run_id': reference['run_id'], 'attempt_id': reference['attempt_id'],
                        'level': reference['level'], 'reset_sequence': owner.solver._notes_boundary(reference)['reset_sequence']}
            generation = str(owner.kernel.generation)
            scope_ids = sorted({w['scope_extractor_id'] for w in self._candidate_witnesses(reference, action)
                                if w.get('scope_extractor_id') is not None and w.get('model_revision')
                                and w['model_revision']['generation'] == generation})
            payload = json.dumps([observation['frame'][-1], reference, action, boundary, scope_ids], allow_nan=False, separators=(',', ':')).encode()
            packed_input = base64.b64encode(zlib.compress(payload)).decode()
            code = "import p7_research as _p7_r\nimport json as _p7_j\nimport zlib as _p7_z\nimport base64 as _p7_b\nprint(_p7_j.dumps(_p7_r._host_evaluate_action(*_p7_j.loads(_p7_z.decompress(_p7_b.b64decode(" + repr(packed_input) + ")))),allow_nan=False))"
            value, cell_id = await self._cell(code, combined, 'p7-auto-')
            self.registration = value['registration']
            result = value['assessment']
            result['_retained_scope_assessments'] = value.get('retained_scope_assessments', {})
            result.update(model_revision=self.revision(self.registration), cell_id=cell_id)
            result['model_case_status'] = self.model_case_status(result['model_revision'])
            result['backtest'] = self.snapshot_backtest()
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
        if result.get('coverage') is None:
            result['coverage'] = _unavailable_assessment(result['reason'])['coverage']
        result.setdefault('backtest', self.snapshot_backtest())
        result['frame_sha256'] = digest(observation['frame'][-1])
        # Retain only this fresh model result, before applying earlier witnesses;
        # reapplication must not fabricate a new witness in the new revision.
        if action['name'] != 'RESET':
            self._retain_fatal(result, reference, action, result['frame_sha256'],
                               result.get('model_revision'), result.get('result_artifact_id'), 'host_auto')
            self._apply_retained_fatal(result, reference, action)
        key = (reference.get('run_id'), result['frame_sha256'], reference.get('level'), self._action_key(action))
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
