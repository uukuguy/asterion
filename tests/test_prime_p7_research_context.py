"""The research context retains the editable model alongside the WorldMap."""
from tests.test_prime_p7_solver import P7SolverFixture


class TestP7ResearchContext(P7SolverFixture):
    def test_current_context_exposes_detached_top_level_revision_fields(self):
        context = self.solver.current_context()
        for key in ('worldmap', 'task', 'model', 'reports', 'correction',
                    'evidence_sequences', 'workspace_revision', 'observation_ref'):
            self.assertIn(key, context)
        self.assertIn('source_export_ids', context['model'])
        context['model']['source_export_ids'].append('sentinel-local-mutation')
        self.assertNotIn('sentinel-local-mutation',
                         self.solver.current_context()['model']['source_export_ids'])
        self.assertEqual(self.engine.calls, [])
