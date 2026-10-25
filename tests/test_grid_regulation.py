from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from asterion.applications.grid_regulation import (
    RegulationCitation,
    RegulationCitationError,
    RegulationQuery,
    cite_regulation,
    lookup_measures,
    write_demo_corpus,
)
from asterion.applications.grid_regulation.answer import (
    ScriptedGridResearch,
    answer_fault,
    fault_prompt,
)
from asterion.applications.grid_regulation.live import (
    GRID_CANCEL_SECONDS,
    GRID_CONTEXT_POLICY,
    GRID_MAX_TURNS,
    LiveGridResearch,
    _Cancel,
    answer_evidence_path,
    arm_grid_cancel,
    build_grid_options,
    exact_directory,
    grid_run_id,
    operator_evidence_root,
    repository_root,
)
from asterion.documents import write_docx, write_pdf

PROJECT = Path(__file__).resolve().parents[1]


class GridRegulationTests(unittest.IsolatedAsyncioTestCase):
    async def test_citation_uses_document_anchors_and_hides_span_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_demo_corpus(root)
            citation = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx,pdf",
            )
            patrol = await cite_regulation(
                root,
                RegulationQuery("5.2", "DL/T 9000-2024", "每季度一次"),
                document_tools="docx,pdf",
            )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="pdf",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.3", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx,pdf",
                )

        self.assertEqual(citation.calls, ("document-read",))
        self.assertEqual(citation.anchors[0]["document"], "grounding.docx")
        self.assertEqual(citation.anchors[0]["kind"], "docx-paragraph")
        self.assertEqual(patrol.anchors[0]["document"], "patrol.pdf")
        self.assertEqual(patrol.anchors[0]["position"]["page"], 1)
        rendered = repr((citation, patrol))
        for secret in ("SECRET-SPAN-BODY", "SECRET-MARKDOWN", "SECRET-OTHER-PAGE"):
            self.assertNotIn(secret, rendered)

    def test_example_prints_anchors_without_a_model(self) -> None:
        completed = subprocess.run(
            [sys.executable, "examples/applications/grid_regulation.py"],
            cwd=PROJECT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["clause_id"], "4.1.2")
        self.assertEqual(payload["anchors"][0]["document"], "grounding.docx")
        self.assertNotIn("SECRET-SPAN-BODY", completed.stdout)
        self.assertNotIn("SECRET-SPAN-BODY", completed.stderr)

    async def test_citation_assembles_a_dotted_clause_across_spans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "station.docx",
                (
                    ("封面 DL/T 9000-2024", None),
                    ("4.1.2 接地电阻", None),
                    ("（1）限值不应大于", None),
                    ("4欧姆。", None),
                    ("4.1.2.1 雨天复测", None),
                    ("4.1.3 其他条款", None),
                    ("2.10 编号不应大于4欧姆。", None),
                ),
            )
            write_pdf(
                root / "station.pdf",
                (
                    (
                        (72, 740, "封面 DL/T 9000-2024"),
                        (72, 700, "4.1.2 接地电阻"),
                        (72, 680, "限值不应大于4欧姆。"),
                        (72, 660, "4.1.3 其他条款"),
                    ),
                ),
            )
            split = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx",
            )
            child = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "雨天复测"),
                document_tools="docx",
            )
            numbered = await cite_regulation(
                root,
                RegulationQuery("2.10", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx",
            )
            pdf = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="pdf",
            )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2.1", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("2.1", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2", "  ", "不应大于4欧姆"),
                    document_tools="docx",
                )
        self.assertEqual(_paragraphs(split), (0, 1, 2, 3))
        self.assertEqual(_paragraphs(child), (0, 1, 4))
        self.assertEqual(_paragraphs(numbered), (0, 6))
        self.assertEqual(
            tuple(
                (anchor["position"]["item"], anchor["position"]["y"])
                for anchor in pdf.anchors
            ),
            ((0, 740), (1, 700), (2, 680)),
        )
        self.assertTrue(
            all(
                anchor["kind"] == "pdf-text" and anchor["position"]["page"] == 1
                for anchor in pdf.anchors
            )
        )
        for citation in (split, child, numbered, pdf):
            self.assertEqual(
                citation.calls,
                tuple("document-read" for _anchor in citation.anchors),
            )
            rendered = repr(citation)
            self.assertNotIn("不应大于4欧姆", rendered)
            self.assertNotIn("雨天复测", rendered)

    async def test_repeated_clause_id_does_not_keep_the_earlier_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "repeat.docx",
                (
                    ("封面 DL/T 9000-2024", None),
                    ("4.1.2 接地电阻", None),
                    ("本节只说明范围。", None),
                    ("4.1.3 其他条款", None),
                    ("4.1.2 接地电阻", None),
                    ("限值不应大于4欧姆。", None),
                ),
            )
            citation = await cite_regulation(
                root,
                RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                document_tools="docx",
            )
        self.assertEqual(
            tuple(
                (anchor["document"], anchor["position"]["paragraph"])
                for anchor in citation.anchors
            ),
            (("repeat.docx", 0), ("repeat.docx", 4), ("repeat.docx", 5)),
        )

    async def test_clause_without_a_version_span_is_not_cited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "bare.docx",
                (("4.1.2 接地电阻不应大于4欧姆。", None),),
            )
            with self.assertRaises(RegulationCitationError):
                await cite_regulation(
                    root,
                    RegulationQuery("4.1.2", "DL/T 9000-2024", "不应大于4欧姆"),
                    document_tools="docx",
                )

    async def test_measures_keep_the_narrowest_matching_clause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _station(root)
            child = await lookup_measures(
                root,
                "雨天复测",
                document="station.docx",
                document_tools="docx",
            )
            parent = await lookup_measures(
                root,
                "限值 雨天复测",
                document="station.docx",
                document_tools="docx",
            )
            both = await lookup_measures(
                root,
                "不应大于4欧姆",
                document="station.docx",
                document_tools="docx",
            )
            opened = await lookup_measures(
                root,
                "不应大于4欧姆",
                document=None,
                document_tools="docx,pdf",
            )
            with self.assertRaises(RegulationCitationError):
                await lookup_measures(
                    root,
                    "应如何处置",
                    document="station.docx",
                    document_tools="docx",
                )
            with self.assertRaises(RegulationCitationError):
                await lookup_measures(
                    root,
                    "封面",
                    document="station.docx",
                    document_tools="docx",
                )
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in child.clauses),
            (("measure", "4.1.2.1"), ("parent", "4.1.2"), ("reference", "2.10")),
        )
        self.assertNotIn("雨天复测", child.clauses[1]["measures"])
        self.assertEqual(child.clauses[0]["basis"]["position"]["paragraph"], 4)
        self.assertEqual(
            child.calls, ("document-read", "document-read", "document-read")
        )
        self.assertNotIn("text", child.clauses[0]["basis"])
        self.assertNotIn("雨天复测", repr(child.clauses[0]["basis"]))
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in parent.clauses),
            (("measure", "4.1.2"), ("reference", "2.10")),
        )
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in both.clauses),
            (("measure", "4.1.2"), ("measure", "2.10"), ("child", "4.1.2.1")),
        )
        self.assertEqual(both.calls, ("document-read",) * 3)
        self.assertTrue(
            all(item["document"] == "station.docx" for item in both.clauses)
        )
        self.assertIn("station.pdf", {item["document"] for item in opened.clauses})
        self.assertNotIn("不应大于4欧姆", repr(both.clauses[0]["basis"]))

    async def test_measures_follow_body_headings_named_by_the_outline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _outline_docx(root / "outline.docx")
            found = await lookup_measures(
                root,
                "不应大于4欧姆",
                document="outline.docx",
                document_tools="docx",
            )
        self.assertEqual(
            tuple((item["relation"], item["clause_id"]) for item in found.clauses),
            (("measure", "4.1.2"), ("child", "4.1.2.1")),
        )
        measure = found.clauses[0]
        self.assertEqual(measure["basis"]["position"], {"paragraph": 5})
        self.assertEqual(
            measure["measures"],
            "4.1.2 接地限值不应大于4欧姆。附注留在本条款内",
        )
        self.assertEqual(found.clauses[1]["measures"], "4.1.2.1 雨天复测")
        self.assertNotIn("接地限值 9", measure["measures"])
        self.assertFalse(found.limited)
        self.assertEqual(found.calls, ("document-read", "document-read"))

    async def test_a_bare_clause_number_does_not_start_a_clause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _bare_number_docx(root / "table.docx")
            kept = await lookup_measures(
                root,
                "不应大于4欧姆",
                document="table.docx",
                document_tools="docx",
            )
            titled = await lookup_measures(
                root,
                "两端接地",
                document="table.docx",
                document_tools="docx",
            )
        self.assertEqual(
            tuple(item["clause_id"] for item in kept.clauses),
            ("4.1.2",),
        )
        self.assertEqual(
            kept.clauses[0]["measures"],
            "4.1.2 接地限值不应大于4欧姆。5.82.10.后续仍属本条。",
        )
        self.assertEqual(titled.clauses[0]["clause_id"], "4.2.1")
        self.assertEqual(titled.clauses[0]["basis"]["kind"], "docx-cell")
        self.assertEqual(titled.clauses[0]["measures"], "4.2.1 两端接地。")


class GridFaultAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_opened_passages_keep_heading_labels_and_drop_digests(self) -> None:
        question = "示范设备发生故障后如何处置"
        reply = "示范答复：按打开的行处理，并见所引位置。\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _desk(root / "desk.docx")
            research = ScriptedGridResearch(reply)
            found = await answer_fault(
                root,
                document="desk.docx",
                question=question,
                research=research,
                document_tools="docx",
            )
        self.assertIsNotNone(research.corpus)
        assert research.corpus is not None
        self.assertFalse(research.corpus.exists())
        self.assertEqual(research.mode, 0o700)
        self.assertIsNone(research.contents)
        prompt = fault_prompt("desk.docx", question)
        self.assertEqual(research.prompt, prompt)
        self.assertEqual(research.input_text, prompt)
        self.assertIn("Follow a citation with another search", prompt)
        self.assertIn("only when this question depends on", prompt)
        self.assertIn("One read covers the leaf", prompt)
        self.assertIn(f"This run allows {GRID_MAX_TURNS} tool turns", prompt)
        self.assertIn("rg -n", prompt)
        self.assertIn("minus at least one", prompt)
        self.assertIn("never below 1", prompt)
        self.assertNotIn("next few lines", prompt)
        self.assertNotIn("Continue while an opened passage cites", prompt)
        self.assertNotIn("six-digit id itself is the read offset", prompt)
        self.assertNotIn("P###### is the read offset", prompt)
        self.assertNotIn(str(root), prompt)
        self.assertEqual(found.document, "desk.docx")
        self.assertEqual(found.reply, reply[:-1])
        self.assertEqual(found.calls, ("bash", "read", "read"))
        self.assertEqual(
            tuple(item["document"] for item in found.evidence),
            ("desk.docx", "desk.docx", "desk.docx"),
        )
        self.assertEqual(
            tuple(item["kind"] for item in found.evidence),
            ("docx-cell", "docx-cell", "docx-paragraph"),
        )
        self.assertNotIn("label", found.evidence[0])
        self.assertNotIn("label", found.evidence[1])
        self.assertEqual(found.evidence[2]["label"], "5.2")
        self.assertEqual(found.evidence[0]["position"]["cell"], 0)
        self.assertEqual(found.evidence[1]["position"]["cell"], 1)
        for item in found.evidence:
            self.assertEqual(
                set(item) - {"label"},
                {"document", "kind", "position"},
            )
        rendered = repr(research.result)
        self.assertNotIn("不应大于4欧姆", rendered)
        self.assertNotIn("雨天", rendered)
        self.assertNotIn(question, rendered)

    async def test_a_repeated_read_stays_one_evidence_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _desk(root / "desk.docx")
            research = ScriptedGridResearch(passage_lines=(3, 3, 2))
            found = await answer_fault(
                root,
                document="desk.docx",
                question="示范设备故障",
                research=research,
                document_tools="docx",
            )
        self.assertEqual(len(found.evidence), 3)
        self.assertEqual(found.calls, ("bash", "read", "read", "read"))

    async def test_no_passage_read_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _desk(root / "desk.docx")
            research = ScriptedGridResearch(passage_lines=())
            with self.assertRaises(RegulationCitationError) as raised:
                await answer_fault(
                    root,
                    document="desk.docx",
                    question="示范设备故障",
                    research=research,
                    document_tools="docx",
                )
        self.assertEqual(str(raised.exception), "regulation measures are unavailable")
        self.assertIsNotNone(research.corpus)
        assert research.corpus is not None
        self.assertFalse(research.corpus.exists())
        self.assertEqual(research.input_text, research.prompt)

        class _NoAnchors:
            async def run(self, *, corpus, prompt, signal):
                del corpus, prompt, signal
                return ("未见处置。", {"paths": ("contents.txt",)}, ("read",))

        with self.assertRaises(RegulationCitationError) as raised:
            await answer_fault(
                root,
                document="desk.docx",
                question="示范设备故障",
                research=_NoAnchors(),
                document_tools="docx",
            )
        self.assertEqual(str(raised.exception), "regulation measures are unavailable")

    async def test_checks_run_before_a_projection_directory_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _desk(root / "desk.docx")
            cases = (
                (None, "desk.docx", "docx", "request is invalid"),
                ("", "desk.docx", "docx", "regulation measures are unavailable"),
                ("   ", "desk.docx", "docx", "regulation measures are unavailable"),
                (
                    "测" * 201,
                    "desk.docx",
                    "docx",
                    "regulation measures are unavailable",
                ),
                ("示范设备故障", "", "docx", "request is invalid"),
                (
                    "示范设备故障",
                    "desk.docx",
                    "pdf",
                    "regulation measures are unavailable",
                ),
                (
                    "示范设备故障",
                    "../desk.docx",
                    "docx",
                    "regulation measures are unavailable",
                ),
                ("示范设备故障", "desk.docx", "pdf,docx", "request is invalid"),
            )
            for question, document, tools, message in cases:
                with self.subTest(question=question, document=document, tools=tools):
                    with patch(
                        "asterion.applications.grid_regulation.answer.tempfile.mkdtemp"
                    ) as made:
                        with self.assertRaises(RegulationCitationError) as raised:
                            await answer_fault(
                                root,
                                document=document,
                                question=question,
                                research=ScriptedGridResearch(),
                                document_tools=tools,
                            )
                    self.assertEqual(str(raised.exception), message)
                    made.assert_not_called()

    async def test_directory_file_is_the_navigation_text(self) -> None:
        question = "示范设备故障"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _heading_docx(root / "desk.docx")
            research = ScriptedGridResearch(passage_lines=(1,))
            found = await answer_fault(
                root,
                document="desk.docx",
                question=question,
                research=research,
                document_tools="docx",
            )
        self.assertEqual(
            research.contents,
            "P000001\tH1\t4.1.2 接地限值\topening-ends P000002\n"
            "P000003\tH2\t5.2 随后的复测。\topening-ends P000003\n",
        )
        self.assertNotIn("正文一句。", research.contents or "")
        self.assertEqual(found.evidence[0]["label"], "4.1.2")
        self.assertNotIn("正文一句。", repr(research.result))

    def test_answer_module_does_not_search_or_walk_clauses(self) -> None:
        source = (
            PROJECT / "src/asterion/applications/grid_regulation/answer.py"
        ).read_text(encoding="utf-8")
        chain = (
            PROJECT
            / "src/asterion/capabilities/dci/implementation/research/directive.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("lookup_chain", source)
        self.assertNotIn("search_documents", source)
        self.assertNotIn("search_documents", chain)
        self.assertNotIn("grid_regulation", chain)


class GridLiveOptionTests(unittest.IsolatedAsyncioTestCase):
    def test_exact_directory_rejects_a_symlink_component(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory)
            resolved = raw.resolve()
            if str(raw) != str(resolved):
                with self.assertRaises(RegulationCitationError) as raised:
                    exact_directory(str(raw), require_directory=True)
                self.assertEqual(
                    str(raised.exception), "regulation measures are unavailable"
                )
                self.assertNotIn(str(raw), str(raised.exception))
            self.assertEqual(
                exact_directory(str(resolved), require_directory=True),
                str(resolved),
            )
            real = resolved / "real"
            real.mkdir()
            link = resolved / "link"
            link.symlink_to(real, target_is_directory=True)
            with self.assertRaises(RegulationCitationError) as raised:
                exact_directory(str(link), require_directory=True)
            self.assertEqual(
                str(raised.exception), "regulation measures are unavailable"
            )
            self.assertNotIn(str(link), str(raised.exception))
            marker = resolved / "marker.txt"
            marker.write_text("x", encoding="utf-8")
            with self.assertRaises(RegulationCitationError) as raised:
                exact_directory(str(marker), require_directory=True)
            self.assertNotIn(str(marker), str(raised.exception))

    def test_builder_keeps_one_resolved_directory_and_separate_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            tree = _pi_tree(base)
            raw = Path(tempfile.mkdtemp(prefix="asterion-grid-corpus-"))
            self.addCleanup(shutil.rmtree, raw, ignore_errors=True)
            corpus = raw
            passage = "P000001\tok\n"
            (corpus / "passages.txt").write_text(passage, encoding="utf-8")
            evidence_parent = Path(tempfile.mkdtemp(prefix="asterion-grid-evidence-"))
            self.addCleanup(shutil.rmtree, evidence_parent, ignore_errors=True)
            evidence_root = evidence_parent / "kept"
            evidence_root.mkdir(mode=0o755)
            env = _live_env(tree, ASTERION_DCI_CORPUS_ROOT=str(base / "wiki"))
            options = build_grid_options(
                corpus,
                env,
                evidence_root=evidence_root,
                which=_which(tree["node"]),
                repo=base,
            )
            resolved = str(corpus.resolve())
            cwd = options.runtime_options["cwd"]
            self.assertEqual(cwd, resolved)
            self.assertEqual(
                options.host_service_options["corpus.local-root"]["root"], cwd
            )
            self.assertEqual(
                sorted(path.name for path in Path(cwd).iterdir()), ["passages.txt"]
            )
            self.assertEqual(
                (Path(cwd) / "passages.txt").read_text(encoding="utf-8"), passage
            )
            evidence = Path(options.runtime_options["evidence_root"])
            self.assertNotEqual(evidence, Path(cwd))
            self.assertFalse(
                _path_within(evidence, Path(cwd)) or _path_within(Path(cwd), evidence)
            )
            self.assertTrue(evidence.is_dir())
            self.assertFalse(evidence.is_symlink())
            self.assertEqual(
                stat.S_IMODE(evidence.stat(follow_symlinks=False).st_mode), 0o700
            )
            self.assertEqual(list(evidence.iterdir()), [])
            self.assertRegex(options.run_id, r"^grid-[0-9a-f]{32}$")
            digest = hashlib.sha256(options.run_id.encode()).hexdigest()
            self.assertEqual(options.evidence_file, evidence / digest / "final.txt")
            self.assertFalse(options.evidence_file.exists())
            self.assertEqual(options.runtime_options["tools"], "read,bash")
            self.assertEqual(options.runtime_options["max_turns"], "32")
            self.assertEqual(GRID_MAX_TURNS, "32")
            self.assertEqual(
                options.runtime_options["context_policy"], GRID_CONTEXT_POLICY
            )
            self.assertEqual(
                GRID_CONTEXT_POLICY,
                json.dumps(
                    {"tool_result_chars": 20000}, sort_keys=True, separators=(",", ":")
                ),
            )
            command = [
                str(tree["node"].resolve()),
                str(tree["cli"]),
                "--mode",
                "rpc",
                "--thinking",
                "off",
            ]
            self.assertEqual(
                options.runtime_options["command"],
                json.dumps(command, ensure_ascii=False, separators=(",", ":")),
            )
            loaded = json.loads(options.runtime_options["environment"])
            self.assertEqual(
                options.runtime_options["environment"],
                json.dumps(
                    loaded, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
            self.assertEqual(list(loaded), sorted(loaded))
            self.assertEqual(
                loaded["PI_CODING_AGENT_DIR"], str(tree["agent"].resolve())
            )
            self.assertEqual(
                loaded["ASTERION_DCI_CORPUS_ROOT"], env["ASTERION_DCI_CORPUS_ROOT"]
            )
            self.assertNotEqual(cwd, loaded["ASTERION_DCI_CORPUS_ROOT"])
            self.assertEqual(
                set(options.runtime_options),
                {
                    "command",
                    "context_policy",
                    "cwd",
                    "environment",
                    "evidence_root",
                    "max_turns",
                    "model",
                    "provider",
                    "tools",
                },
            )
            self.assertTrue(
                all(type(value) is str for value in options.runtime_options.values())
            )
            again = build_grid_options(
                corpus,
                env,
                evidence_root=evidence,
                which=_which(tree["node"]),
                repo=base,
                run_id="grid-" + "ab" * 16,
            )
            self.assertEqual(again.runtime_options["evidence_root"], str(evidence))
            self.assertEqual(
                again.evidence_file,
                answer_evidence_path(str(evidence), again.run_id),
            )
            self.assertTrue(evidence.is_dir())

    def test_builder_rejects_nested_evidence_and_missing_wiring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            tree = _pi_tree(base)
            corpus = base / "corpus"
            corpus.mkdir()
            (corpus / "passages.txt").write_text("P000001\tok\n", encoding="utf-8")
            env = _live_env(tree)
            hidden = corpus / "hidden"
            with self.assertRaises(RegulationCitationError) as raised:
                build_grid_options(
                    corpus,
                    env,
                    evidence_root=hidden,
                    which=_which(tree["node"]),
                    repo=base,
                )
            self.assertEqual(
                str(raised.exception), "regulation measures are unavailable"
            )
            self.assertFalse(hidden.exists())
            with self.assertRaises(RegulationCitationError):
                build_grid_options(
                    corpus,
                    env,
                    evidence_root=corpus,
                    which=_which(tree["node"]),
                    repo=base,
                )
            outer = base / "outer"
            outer.mkdir()
            inner = outer / "corpus"
            inner.mkdir()
            (inner / "passages.txt").write_text("x\n", encoding="utf-8")
            with self.assertRaises(RegulationCitationError):
                build_grid_options(
                    inner,
                    env,
                    evidence_root=outer,
                    which=_which(tree["node"]),
                    repo=base,
                )
            self.assertTrue(inner.is_dir())
            absent = base / "not-created"
            with self.assertRaises(RegulationCitationError) as raised:
                build_grid_options(
                    corpus,
                    {
                        "DCI_MODEL": "demo-model",
                        "DCI_PROVIDER": "SECRET-PROVIDER-VALUE ",
                    },
                    evidence_root=absent,
                    which=_which(tree["node"]),
                    repo=base,
                )
            self.assertEqual(
                str(raised.exception), "regulation measures are unavailable"
            )
            self.assertNotIn("DCI_PROVIDER", str(raised.exception))
            self.assertNotIn("SECRET-PROVIDER-VALUE", str(raised.exception))
            self.assertFalse(absent.exists())
            cases = (
                (
                    "DCI_MODEL",
                    "SECRET MODEL",
                    {**env, "DCI_MODEL": "SECRET MODEL"},
                    _which(tree["node"]),
                ),
                (
                    "DCI_PI_DIR",
                    "SECRET-CHECKOUT",
                    {**env, "DCI_PI_DIR": str(base / "SECRET-CHECKOUT")},
                    _which(tree["node"]),
                ),
                (
                    "DCI_PI_AGENT_DIR",
                    "SECRET-AGENT-MISSING",
                    {**env, "DCI_PI_AGENT_DIR": str(base / "SECRET-AGENT-MISSING")},
                    _which(tree["node"]),
                ),
                (
                    "node",
                    "SECRET-NODE",
                    env,
                    lambda name: "SECRET-NODE",
                ),
            )
            (base / "SECRET-CHECKOUT").mkdir()
            for key, sentinel, case_env, which in cases:
                with self.subTest(key=key):
                    target = base / f"evidence-{key}"
                    with self.assertRaises(RegulationCitationError) as raised:
                        build_grid_options(
                            corpus,
                            case_env,
                            evidence_root=target,
                            which=which,
                            repo=base,
                        )
                    self.assertEqual(
                        str(raised.exception), "regulation measures are unavailable"
                    )
                    self.assertNotIn(key, str(raised.exception))
                    self.assertNotIn(sentinel, str(raised.exception))
                    self.assertFalse(target.exists())
            tree["node"].chmod(0o644)
            with self.assertRaises(RegulationCitationError) as raised:
                build_grid_options(
                    corpus,
                    env,
                    evidence_root=base / "evidence-mode",
                    which=_which(tree["node"]),
                    repo=base,
                )
            self.assertNotIn(str(tree["node"]), str(raised.exception))

    def test_construction_does_not_create_evidence_or_call_pi(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            missing = base / "operator-evidence"
            research = LiveGridResearch({}, evidence_root=missing, repo=base)
            self.assertFalse(missing.exists())
            self.assertNotIn(
                "prepare_native_application", research.__init__.__code__.co_names
            )
            fake = base / "repo"
            fake.mkdir()
            self.assertEqual(
                operator_evidence_root(fake), fake / "outputs" / "grid-regulation"
            )
            self.assertFalse(operator_evidence_root(fake).exists())
        self.assertNotIn(
            "prepare_native_application", build_grid_options.__code__.co_names
        )
        self.assertNotIn("project_document", build_grid_options.__code__.co_names)
        self.assertIn(
            "prepare_native_application", LiveGridResearch.run.__code__.co_names
        )
        source = (
            PROJECT / "src/asterion/applications/grid_regulation/live.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("dci.evaluation", source)
        self.assertNotIn("ASTERION_DCI_CORPUS_ROOT", source)
        self.assertNotIn("load_dotenv", source)
        self.assertNotIn("project_document", source)
        page = (
            PROJECT / "src/asterion/applications/grid_regulation/page.py"
        ).read_text(encoding="utf-8")
        self.assertIn("research=LiveGridResearch(", page)
        self.assertIn("load_dotenv(env_file, override=False)", page)
        self.assertIn("operator_evidence_root(repo)", page)
        self.assertNotIn("research=UnavailableResearch()", page)
        self.assertNotIn("prepare_native_application", page)
        self.assertNotIn("asterion.runtimes", page)
        self.assertIn("UnavailableResearch()", page)
        example = (PROJECT / "examples/applications/native_dci.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"tools": "read,grep"', example)
        root = repository_root()
        self.assertTrue((root / "pyproject.toml").is_file())
        self.assertRegex(grid_run_id(), r"^grid-[0-9a-f]{32}$")
        marked = "grid-é"
        self.assertEqual(
            answer_evidence_path("/evidence", marked),
            Path("/evidence")
            / hashlib.sha256(marked.encode("utf-8")).hexdigest()
            / "final.txt",
        )

    async def test_cancel_is_armed_for_300_seconds(self) -> None:
        cancel = _Cancel()
        self.assertFalse(cancel.cancelled)
        loop = asyncio.get_running_loop()
        handle = arm_grid_cancel(cancel)
        self.assertEqual(GRID_CANCEL_SECONDS, 300)
        self.assertAlmostEqual(
            handle.when() - loop.time(), GRID_CANCEL_SECONDS, delta=1
        )
        handle.cancel()
        self.assertFalse(cancel.cancelled)
        cancel.cancel()
        self.assertTrue(cancel.cancelled)


def _pi_tree(base: Path) -> dict[str, Path]:
    node = base / "node"
    node.write_text("#!/bin/sh\n", encoding="utf-8")
    node.chmod(0o755)
    checkout = base / "checkout"
    cli = checkout / "packages/coding-agent/dist/cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("//\n", encoding="utf-8")
    agent = base / "agent"
    agent.mkdir()
    return {"node": node, "checkout": checkout, "cli": cli, "agent": agent}


def _live_env(tree: dict[str, Path], **extra: str) -> dict[str, str]:
    env = {
        "DCI_PROVIDER": "demo.provider",
        "DCI_MODEL": "demo-model",
        "DCI_PI_DIR": str(tree["checkout"]),
        "DCI_PI_AGENT_DIR": str(tree["agent"]),
    }
    env.update(extra)
    return env


def _which(node: Path):
    def which(name: str) -> str | None:
        return str(node) if name == "node" else None

    return which


def _path_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return path != parent


def _desk(path: Path) -> None:
    write_docx(
        path,
        (("4.1.2 接地限值", None), ("5.2 随后的复测。", None)),
        ((("雨天", "不应大于4欧姆。见5.2。"),),),
    )


def _heading_docx(path: Path) -> None:
    paragraphs = (
        ("1", "4.1.2 接地限值"),
        ("", "正文一句。"),
        ("2", "5.2 随后的复测。"),
    )
    body: list[str] = []
    for style, text in paragraphs:
        properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body.append(f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document)


def _bare_number_docx(path: Path) -> None:
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>4.1.2 接地限值</w:t></w:r></w:p>
<w:p><w:r><w:t>不应大于4欧姆。</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>5.8</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
<w:p><w:r><w:t>2.10.</w:t></w:r></w:p>
<w:p><w:r><w:t>后续仍属本条。</w:t></w:r></w:p>
<w:p><w:r><w:t>4.1.3 其他条款</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>4.2.1 两端接地。</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>
"""
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document)


def _outline_docx(path: Path) -> None:
    paragraphs = (
        ("TOC1", "1. 总则 1"),
        ("TOC2", "4.1.2. 接地限值 9"),
        ("TOC3", "4.1.2.1. 雨天复测 2"),
        ("TOC2", "4.2.1. 其他条款 3"),
        ("1", "总则"),
        ("2", "接地限值"),
        ("", "不应大于4欧姆。"),
        ("4", "附注留在本条款内"),
        ("3", "雨天复测"),
        ("2", "其他条款"),
    )
    body: list[str] = []
    for style, text in paragraphs:
        properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        body.append(f"<w:p>{properties}<w:r><w:t>{text}</w:t></w:r></w:p>")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body)}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("word/document.xml", document)


def _station(root: Path) -> None:
    write_docx(
        root / "station.docx",
        (
            ("封面 DL/T 9000-2024", None),
            ("4.1.2 接地电阻", None),
            ("（1）限值不应大于", None),
            ("4欧姆。", None),
            ("4.1.2.1 雨天复测，见2.10。", None),
            ("4.1.3 其他条款", None),
            ("2.10 编号不应大于4欧姆。", None),
        ),
    )
    write_pdf(
        root / "station.pdf",
        (
            (
                (72, 740, "封面 DL/T 9000-2024"),
                (72, 700, "4.1.2 接地电阻"),
                (72, 680, "限值不应大于4欧姆。"),
                (72, 660, "4.1.3 其他条款"),
            ),
        ),
    )


def _paragraphs(citation: RegulationCitation) -> tuple[int, ...]:
    return tuple(anchor["position"]["paragraph"] for anchor in citation.anchors)
