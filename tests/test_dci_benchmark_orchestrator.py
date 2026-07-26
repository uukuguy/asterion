from __future__ import annotations

import unittest

from tools.dci_benchmark_orchestrator import select_tasks


class BenchmarkInventoryTests(unittest.TestCase):
    def test_suites_have_stable_ordered_membership(self) -> None:
        github = select_tasks("github")
        paper = select_tasks("paper-main")
        combined = select_tasks("all")

        self.assertEqual(len(github), 12)
        self.assertEqual(len(paper), 13)
        self.assertEqual(len(combined), 15)
        self.assertEqual(len({task.task_id for task in combined}), 15)
        self.assertEqual(
            tuple(task.task_id for task in combined),
            (
                "bcplus.level3",
                "bcplus.main",
                "beir.arguana",
                "beir.scifact",
                "bright.biology",
                "bright.earth-science",
                "bright.economics",
                "bright.robotics",
                "qa.2wikimultihopqa",
                "qa.bamboogle.github-sample50",
                "qa.bamboogle.paper-full125",
                "qa.hotpotqa",
                "qa.musique",
                "qa.nq",
                "qa.triviaqa",
            ),
        )

    def test_bamboogle_variants_are_not_deduplicated(self) -> None:
        tasks = {task.task_id: task for task in select_tasks("all")}
        github = tasks["qa.bamboogle.github-sample50"]
        paper = tasks["qa.bamboogle.paper-full125"]

        self.assertEqual(github.selection_variant, "github-sample50")
        self.assertEqual(paper.selection_variant, "paper-full125")
        self.assertIsNotNone(github.launcher)
        self.assertIsNone(paper.launcher)
        self.assertEqual(
            paper.dataset, "paper-full/data/bamboogle/test-125.jsonl"
        )

    def test_paper_ir_tasks_label_asterion_metric_semantics(self) -> None:
        ir_tasks = (
            task
            for task in select_tasks("paper-main")
            if task.profile.startswith(("beir.", "bright."))
        )
        for task in ir_tasks:
            with self.subTest(task=task.task_id):
                self.assertIn("Asterion-defined", task.note)


if __name__ == "__main__":
    unittest.main()
