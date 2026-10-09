"""P7 meaning for Prime's passive private research relationships.

Accepted notes/revisions are explicit model statements. Programs and submitted
experiments are observed behavior. Temporal adjacency is the only inferred link;
neither matching feedback nor a later note certifies the model's explanation.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from asterion.agents.prime.research_record import ResearchRecordStore
from .research import copy_json


class P7ResearchChain:
    def __init__(self, *, run_root: Path, workspace):
        self.root = run_root.resolve()
        self.workspace = workspace
        self.workspace_root = self.root / workspace.root.relative_to(run_root)
        self.unavailable_count = 0
        self.store = None
        try:
            self.store = ResearchRecordStore(path=self.root / 'research' / 'research-chain.json',
                                             scope=workspace.scope)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.unavailable_count += 1

    def _reference(self, path: Path, kind: str, **metadata):
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError('research evidence unavailable')
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError('research evidence unavailable')
        raw = path.read_bytes()
        return dict(kind=kind, path=path.relative_to(self.root).as_posix(),
                    sha256='sha256:' + sha256(raw).hexdigest(), **metadata)

    def _append(self, **record):
        if self.store is None:
            self.unavailable_count += 1
            return
        try:
            self.store.append(**record)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            # Research indexing never changes accepted notes or action outcomes.
            self.unavailable_count += 1

    def workspace_result(self, result):
        if result.get('status') not in {'noted', 'revised', 'published'}:
            return
        try:
            current = self.workspace.read(result['workspace_revision'])
            revision = current['workspace_revision']
            refs = [self._reference(self.workspace_root / 'revisions' / (revision[7:] + '.json'),
                                    'workspace_revision', revision=revision)]
            if result['status'] == 'noted':
                note = self.workspace.notes_read(result['notes_revision'])
                note_record = self.workspace.memory.read(note['revision'])
                refs.append(self._reference(self.workspace_root / 'memory' / 'revisions' / (note['revision'][7:] + '.json'),
                                            'notes_revision', revision=note['revision']))
                refs.append({'kind': 'observation', **note['observation_ref']})
                statement = {'preview': note['text'][:600], 'preview_truncated': len(note['text']) > 600,
                             'parent_notes_revision': note_record['parent_revision']}
                kind, key = 'notes', note['revision']
            else:
                statement = {'preview': current['worldmap']['description_zh'][:600],
                             'preview_truncated': len(current['worldmap']['description_zh']) > 600,
                             'correction': current['correction'], 'parent_workspace_revision': current['parent_revision']}
                refs.extend({'kind': 'action_sequence', 'sequence': sequence}
                            for sequence in current['evidence_sequences'])
                kind, key = 'model_revision', revision
            self._append(key=key, kind=kind, origin='model_statement', statement=statement, evidence_refs=refs)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.unavailable_count += 1

    def computation(self, kernel, start):
        if start is None:
            self.unavailable_count += 1
            return
        try:
            items = kernel.cell_history(start=start, limit=1)['items']
            if not items:
                self.unavailable_count += 1
                return
            cell = items[0]
            ref = self._reference(self.root / 'research-kernel' / 'cells' / (cell['cell_id'][5:] + '.json'),
                                  'cell', **cell)
            self._append(key=cell['cell_id'], kind='computation', origin='behavioral_evidence',
                         statement={'execution_status': cell['status'],
                                    'completion': {'ok': 'completed', 'python-error': 'failed',
                                                   'interrupted': 'interrupted'}.get(cell['status'], 'unknown')},
                         evidence_refs=[ref])
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.unavailable_count += 1

    def experiment(self, plan, result, transitions):
        if result.get('status') != 'recorded':
            return
        try:
            refs = [{'kind': 'observation', **plan['start']},
                    {'kind': 'observation', **result['observation_ref']}]
            for transition in transitions:
                refs.append({'kind': 'transition', 'sequence': transition.sequence,
                             'before_sha256': transition.before_sha256, 'after_sha256': transition.after_sha256})
            statement = {'submitted_plan': copy_json(plan), 'submitted_plan_origin': 'model_statement',
                         'feedback_origin': 'environment', 'stop_reason': result['stop_reason'],
                         'applied_count': result['applied_count'], 'feedback': result['feedback'],
                         'outcome_known': result['stop_reason'] not in {'unknown', 'environment-result-unknown'}}
            self._append(key='plan:' + plan['plan_id'], kind='experiment', origin='behavioral_evidence',
                         statement=statement, evidence_refs=refs)
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.unavailable_count += 1

    def summary(self):
        summary = self.store.summary() if self.store is not None else {
            'record_count': 0, 'omitted_record_count': 0, 'omitted_reference_count': 0}
        return {**summary, 'unavailable_record_count': self.unavailable_count}
