"""Stateless, lossless P7 board delivery at the model-facing application edge.

Private research readers, recorded evidence and Solver values stay raw. This
projection names every omitted mutation echo; extensions require review.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy

from .score import canonical_bytes, digest


FRAME_SCHEMA = 'asterion.prime-p7-actor-frame/v1'
FRAME_ENCODING = 'palette-row-dictionary/v1'
FRAME_READ_API = 'p7_research.frame(sequence)'
_SYMBOLS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_'
_MAX_CELLS = 1_048_576
_FRAME_FIELDS = {'schema', 'encoding', 'shape', 'settled_frame_sha256', 'observation_ref', 'read_api'}
_ACK_FIELDS = {
    'status', 'workspace_revision', 'parent_revision', 'scope', 'evidence_sequences',
    'observation_ref', 'budget', 'lifecycle', 'requires_calibration', 'needs_revision',
    'revision_reason', 'environment_result_unknown', 'processing_blocked', 'diagnostics',
    'checkpoint', 'correction', 'projection_truncated',
}
_MUTATION_ECHO_FIELDS = {
    'worldmap', 'model', 'task', 'reports', 'observation', 'experience',
}
ACTOR_FRAME_INSTRUCTION = (
    'observation.frame may use palette-row-dictionary/v1: each row_ids[y] selects rows; '
    'each character at x selects the same-index literal pixel in palette via symbols. '
    'shape [1,H,W] retains a singleton frame layer; [H,W] is a 2D board. '
    'This is the complete settled board, with no inferred object or game meaning. '
    'A numeric frame with frame_delivery.encoding=raw is already decoded. '
    'For an exact raw 2D board use p7_research.frame(sequence) in IPython, taking sequence '
    'from this observation_ref. settled_frame_sha256 hashes the 2D pixel grid and is distinct '
    'from observation_sha256. Revise/publish success returns an acknowledgement; '
    'use p7_workspace op read for the complete current workspace.'
)


class ActorProjectionError(ValueError):
    """Public-safe explicit failure when actor delivery needs contract review."""

    def __init__(self):
        super().__init__('P7 actor delivery schema requires review')


def _shape(value):
    if (type(value) is not list or len(value) not in (2, 3)
            or any(type(v) is not int or not 1 <= v <= _MAX_CELLS for v in value)
            or (len(value) == 3 and value[0] != 1)
            or value[-2] * value[-1] > _MAX_CELLS):
        raise ActorProjectionError
    return value


def _grid(frame):
    if type(frame) is not list or not frame or type(frame[0]) is not list or not frame[0]:
        raise ActorProjectionError
    layered = type(frame[0][0]) is list
    if layered and len(frame) != 1:
        raise ActorProjectionError
    grid = frame[0] if layered else frame
    if type(grid[0]) is not list or not grid[0]:
        raise ActorProjectionError
    shape = _shape(([1] if layered else []) + [len(grid), len(grid[0])])
    if any(type(row) is not list or len(row) != shape[-1]
           or any(type(v) is not int or not 0 <= v <= 255 for v in row) for row in grid):
        raise ActorProjectionError
    return grid, shape


def _reference(value):
    if (type(value) is not dict
            or set(value) != {'run_id', 'attempt_id', 'level', 'sequence', 'observation_sha256'}
            or any(type(value[key]) is not str or not value[key] for key in ('run_id', 'attempt_id'))
            or type(value['level']) is not int or value['level'] < 1
            or type(value['sequence']) is not int or value['sequence'] < 0
            or type(value['observation_sha256']) is not str
            or not value['observation_sha256'].startswith('sha256:')
            or len(value['observation_sha256']) != 71
            or any(c not in '0123456789abcdef' for c in value['observation_sha256'][7:])):
        raise ActorProjectionError
    return deepcopy(value)


def encode_actor_frame(frame, observation_ref):
    """Encode one settled board independently, preserving its original rank."""
    grid, shape = _grid(frame)
    base = {'schema': FRAME_SCHEMA, 'shape': shape,
            'settled_frame_sha256': digest(grid), 'observation_ref': _reference(observation_ref),
            'read_api': FRAME_READ_API}
    palette = sorted({v for row in grid for v in row})
    if len(palette) <= len(_SYMBOLS):
        symbols = _SYMBOLS[:len(palette)]
        lookup = dict(zip(palette, symbols))
        rows, row_ids, indices = [], [], {}
        for row in grid:
            text = ''.join(lookup[v] for v in row)
            if text not in indices:
                indices[text] = len(rows)
                rows.append(text)
            row_ids.append(indices[text])
        encoded = {**base, 'encoding': FRAME_ENCODING, 'palette': palette, 'symbols': symbols,
                   'rows': rows, 'row_ids': row_ids}
        if len(canonical_bytes(encoded)) < len(canonical_bytes(frame)):
            return encoded
        reason = 'compact-encoding-not-smaller'
    else:
        reason = 'palette-exceeds-single-symbol-codec'
    return {**base, 'encoding': 'raw', 'reason': reason, 'frame': deepcopy(frame)}


def decode_actor_frame(value):
    """Validate the closed delivery format and reconstruct the exact board."""
    if type(value) is not dict or value.get('schema') != FRAME_SCHEMA or value.get('read_api') != FRAME_READ_API:
        raise ActorProjectionError
    shape = _shape(value.get('shape'))
    _reference(value.get('observation_ref'))
    if value.get('encoding') == 'raw':
        if (set(value) != _FRAME_FIELDS | {'reason', 'frame'}
                or value['reason'] not in {'compact-encoding-not-smaller', 'palette-exceeds-single-symbol-codec'}):
            raise ActorProjectionError
        grid, actual_shape = _grid(value['frame'])
        if shape != actual_shape:
            raise ActorProjectionError
        frame = deepcopy(value['frame'])
    elif value.get('encoding') == FRAME_ENCODING:
        if set(value) != _FRAME_FIELDS | {'palette', 'symbols', 'rows', 'row_ids'}:
            raise ActorProjectionError
        palette, symbols, rows, row_ids = (value[k] for k in ('palette', 'symbols', 'rows', 'row_ids'))
        if (type(palette) is not list or not 1 <= len(palette) <= len(_SYMBOLS)
                or any(type(v) is not int or not 0 <= v <= 255 for v in palette)
                or palette != sorted(set(palette)) or symbols != _SYMBOLS[:len(palette)]
                or type(rows) is not list or not 1 <= len(rows) <= shape[-2]
                or any(type(row) is not str or len(row) != shape[-1]
                       or any(c not in symbols for c in row) for row in rows)
                or len(set(rows)) != len(rows)
                or type(row_ids) is not list or len(row_ids) != shape[-2]
                or any(type(i) is not int or not 0 <= i < len(rows) for i in row_ids)
                or set(row_ids) != set(range(len(rows)))):
            raise ActorProjectionError
        lookup = dict(zip(symbols, palette))
        grid = [[lookup[c] for c in rows[i]] for i in row_ids]
        frame = [grid] if len(shape) == 3 else grid
    else:
        raise ActorProjectionError
    if digest(grid) != value.get('settled_frame_sha256'):
        raise ActorProjectionError
    return frame


def project_actor_context(context):
    """Preserve all context fields; encode only the settled observation frame."""
    if type(context) is not dict:
        raise ActorProjectionError
    source = context.get('observation')
    if type(source) is not dict or 'frame' not in source:
        raise ActorProjectionError
    if 'frame_delivery' in source:
        raise ActorProjectionError
    # Validate dimensions before allocating copies of the input board.
    encoded = encode_actor_frame(source['frame'], context.get('observation_ref'))
    result = {key: deepcopy(value) for key, value in context.items() if key != 'observation'}
    observation = {key: deepcopy(value) for key, value in source.items() if key != 'frame'}
    result['observation'] = observation
    if encoded['encoding'] == 'raw':
        observation['frame'] = encoded.pop('frame')
        observation['frame_delivery'] = encoded
    else:
        observation['frame'] = encoded
    return result


def project_actor_result(method, params, response):
    """Apply projection only to named successful actor method responses."""
    if method == 'workspace':
        request = params.get('request', params) if isinstance(params, Mapping) else {}
        op = request.get('op') if isinstance(request, Mapping) else None
        if (op, response.get('status')) in {('revise', 'revised'), ('publish', 'published')}:
            if not set(response) <= _ACK_FIELDS | _MUTATION_ECHO_FIELDS:
                raise ActorProjectionError
            return {key: deepcopy(value) for key, value in response.items() if key in _ACK_FIELDS}
        if op == 'read' and 'status' not in response:
            return project_actor_context(response)
    elif method == 'execute_plan' and response.get('status') == 'recorded':
        return project_actor_context(response)
    return deepcopy(response)
