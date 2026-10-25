from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from asterion.applications.grid_regulation.answer import ScriptedGridResearch
from asterion.applications.grid_regulation.live import (
    _desk_progress,
    write_desk_log,
)
from asterion.applications.grid_regulation.page import (
    desk_request_line,
    page_bytes,
    serve,
)
from asterion.applications.grid_regulation.retrieve import write_demo_corpus
from asterion.documents import write_docx
from asterion.runtimes.pi import PI_PROGRESS, _report_pi_progress


class _Body:
    def __init__(self, status: int, headers: object, text: str) -> None:
        self.status = status
        self.headers = headers
        self.text = text


class GridRegulationPageTests(unittest.TestCase):
    def test_page_is_one_local_file_and_cites_the_demo_clause(self) -> None:
        html = page_bytes().decode()
        self.assertIn("规程检索", html)
        self.assertIn("怎么查", html)
        self.assertIn("2023年稳规", html)
        self.assertIn("引用证据", html)
        self.assertIn("查找处置规定", html)
        self.assertIn("正在阅读… ", html)
        self.assertIn("正在阅读这本规程。", html)
        self.assertIn("renderMarkdown", html)
        self.assertIn("groupEvidence", html)
        self.assertIn("item.heading", html)
        self.assertIn("is-key", html)
        self.assertIn("PingFang SC", html)
        self.assertIn("table-scroll", html)
        self.assertNotIn("Songti", html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("这次查找没有完成", html)
        self.assertIn("可以写在答复里", html)
        self.assertIn("主变 冷却全停", html)
        self.assertNotIn("全部已列出的规程", html)
        self.assertNotIn("按条款号找出原句的位置", html)
        self.assertNotIn("按阅读顺序串起", html)
        self.assertNotIn("条款号只写在条款依据里", html)
        self.assertNotIn("每个词至少两个字", html)
        self.assertNotIn("条款号只出现在引用证据里", html)
        self.assertNotIn("没有在这本规程里找到这些字", html)
        page_source = (
            Path(__file__).resolve().parents[1]
            / "src/asterion/applications/grid_regulation/page.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("prepare_native_application", page_source)
        self.assertNotIn("lookup_chain", page_source)
        self.assertNotIn("asterion.runtimes", page_source)
        self.assertEqual(
            desk_request_line("GET", "/?situation=SECRET-SPAN-BODY", 200),
            "GET / 200",
        )
        self.assertNotIn(
            "SECRET",
            desk_request_line("POST", "/api/measures?situation=SECRET", 422),
        )
        seen: list[tuple[str, str]] = []
        token = PI_PROGRESS.set(lambda kind, detail: seen.append((kind, detail)))
        try:
            _report_pi_progress({"type": "turn_start"}, turn=1)
            _report_pi_progress(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "thinking_delta",
                        "delta": "先看目录",
                    },
                }
            )
            _report_pi_progress(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "text_delta",
                        "delta": "SECRET-SPAN-BODY",
                    },
                }
            )
            _report_pi_progress(
                {
                    "type": "tool_execution_start",
                    "toolName": "read",
                    "args": {
                        "path": "/tmp/SECRET-SPAN-BODY/passages.txt",
                        "offset": 12,
                        "limit": 40,
                    },
                }
            )
            _report_pi_progress(
                {
                    "type": "tool_execution_start",
                    "toolName": "bash",
                    "args": {"command": "rg -n SECRET-SPAN-BODY passages.txt"},
                }
            )
            _report_pi_progress({"type": "tool_execution_start", "toolName": "sed"})
            _report_pi_progress(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "text_delta",
                        "delta": "这是最终答复不应出现",
                    },
                }
            )
            _report_pi_progress({"type": "turn_start"}, turn=0)
        finally:
            PI_PROGRESS.reset(token)
        self.assertEqual(
            seen,
            [
                ("turn", "1"),
                ("decision", "先看目录"),
                ("tool", "read passages.txt 12 40"),
                ("tool", "bash passages.txt"),
            ],
        )
        self.assertNotIn("SECRET", " ".join(detail for _, detail in seen))
        later: list[tuple[str, str]] = []
        token = PI_PROGRESS.set(lambda kind, detail: later.append((kind, detail)))
        try:
            _report_pi_progress({"type": "turn_start"}, turn=2)
            _report_pi_progress(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {
                        "type": "text_delta",
                        "delta": "打开叶子" + "甲" * 200,
                    },
                }
            )
            _report_pi_progress(
                {
                    "type": "tool_execution_start",
                    "toolName": "read",
                    "args": {"path": "passages.txt", "offset": 12},
                }
            )
            _report_pi_progress(
                {
                    "type": "tool_execution_start",
                    "toolName": "grep",
                    "args": {"path": "contents.txt", "pattern": "SECRET-SPAN-BODY"},
                }
            )
            _report_pi_progress(
                {
                    "type": "tool_execution_start",
                    "toolName": "bash",
                    "args": {"command": "rg passages.txt.bak SECRET-SPAN-BODY"},
                }
            )
            _report_pi_progress(
                {
                    "type": "tool_execution_start",
                    "toolName": "read",
                    "args": {
                        "path": "../SECRET-SPAN-BODY",
                        "offset": True,
                        "limit": 4,
                    },
                }
            )
        finally:
            PI_PROGRESS.reset(token)
        self.assertEqual(later[0], ("turn", "2"))
        self.assertEqual(later[1][0], "decision")
        self.assertTrue(later[1][1].startswith("打开叶子"))
        self.assertLessEqual(len(later[1][1]), 77)
        self.assertTrue(later[1][1].endswith("…"))
        self.assertEqual(
            later[2:],
            [
                ("tool", "read passages.txt 12"),
                ("tool", "grep contents.txt"),
                ("tool", "bash"),
                ("tool", "read"),
            ],
        )
        self.assertNotIn("SECRET", " ".join(detail for _, detail in later))

        def _reject(kind: str, detail: str) -> None:
            raise RuntimeError(detail)

        token = PI_PROGRESS.set(_reject)
        try:
            _report_pi_progress({"type": "turn_start"}, turn=2)
        finally:
            PI_PROGRESS.reset(token)
        captured = io.StringIO()
        with patch(
            "asterion.applications.grid_regulation.live.sys.stderr",
            captured,
        ):
            write_desk_log("第 1 轮")
            write_desk_log("token SECRET-SPAN-BODY")
            write_desk_log("打开 read\nSECRET-SPAN-BODY")
            _desk_progress("tool", "read passages.txt 12 40")
            _desk_progress("tool", "read passages.txt 12")
            _desk_progress("tool", "read passages.txt")
            _desk_progress("tool", "read")
            _desk_progress("tool", "bash passages.txt")
            _desk_progress("tool", "grep contents.txt")
            _desk_progress("tool", "bash")
            _desk_progress("decision", "先看目录")
            _desk_progress("decision", "secret plan")
        self.assertEqual(
            captured.getvalue(),
            "第 1 轮\n"
            "读 passages.txt 第 12-51 行\n"
            "读 passages.txt 第 12 行起\n"
            "读 passages.txt\n"
            "打开 read\n"
            "搜索 passages.txt\n"
            "搜索 contents.txt\n"
            "搜索\n"
            "决定 先看目录\n",
        )
        self.assertNotIn("SECRET", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("@import", html)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_demo_corpus(root)
            server = serve(root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)
            base = f"http://127.0.0.1:{server.server_address[1]}"
            page = _get(base + "/")
            self.assertEqual(page.status, 200)
            self.assertIn("text/html", page.headers["Content-Type"])
            self.assertIn("规程检索", page.text)
            corpus = json.loads(_get(base + "/api/corpus").text)
            names = [item["document"] for item in corpus["files"]]
            self.assertEqual(names, ["grounding.docx", "patrol.pdf"])
            cited = json.loads(
                _post(
                    base + "/api/cite",
                    {
                        "clause_id": "4.1.2",
                        "version": "DL/T 9000-2024",
                        "finding": "不应大于4欧姆",
                        "document_tools": "docx",
                    },
                ).text
            )
            self.assertEqual(cited["anchors"][0]["document"], "grounding.docx")
            self.assertIn("不应大于4欧姆", cited["anchors"][0]["text"])
            missed = _post(
                base + "/api/cite",
                {
                    "clause_id": "4.1.3",
                    "version": "DL/T 9000-2024",
                    "finding": "不应大于4欧姆",
                    "document_tools": "docx,pdf",
                },
            )
            self.assertEqual(missed.status, 422)
            self.assertEqual(
                json.loads(missed.text)["error"],
                "regulation citation is unavailable",
            )
            self.assertNotIn("SECRET", missed.text)
            question = "示范设备发生故障后如何处置"
            unavailable = _post(
                base + "/api/measures",
                {
                    "situation": question,
                    "document": "grounding.docx",
                    "document_tools": "docx",
                },
            )
            self.assertEqual(unavailable.status, 422)
            self.assertEqual(
                json.loads(unavailable.text)["error"],
                "regulation measures are unavailable",
            )
            self.assertNotIn(question, unavailable.text)
            self.assertNotIn("SECRET", unavailable.text)
            blank = _post(
                base + "/api/measures",
                {
                    "situation": "不应大于4欧姆",
                    "document": "",
                    "document_tools": "docx",
                },
            )
            self.assertEqual(blank.status, 400)
            self.assertEqual(json.loads(blank.text)["error"], "request is invalid")
            rejected = _post(
                base + "/api/measures",
                {
                    "situation": "不应大于4欧姆",
                    "document": "grounding.docx",
                    "document_tools": "pdf,docx",
                },
            )
            self.assertEqual(rejected.status, 400)
            self.assertEqual(json.loads(rejected.text)["error"], "request is invalid")

    def test_scripted_measures_cite_the_opened_row_and_paragraph(self) -> None:
        question = "示范设备发生故障后如何处置"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "desk.docx",
                (("4.1.2 接地限值", None), ("5.2 随后的复测。", None)),
                ((("雨天", "不应大于4欧姆。见5.2。"),),),
            )
            server = serve(root, research=ScriptedGridResearch())
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)
            base = f"http://127.0.0.1:{server.server_address[1]}"
            captured = io.StringIO()
            with patch(
                "asterion.applications.grid_regulation.live.sys.stderr",
                captured,
            ):
                found = json.loads(
                    _post(
                        base + "/api/measures",
                        {
                            "situation": question,
                            "document": "desk.docx",
                            "document_tools": "docx",
                        },
                    ).text
                )
            progress = captured.getvalue()
            self.assertIn("开始阅读\n", progress)
            self.assertIn("阅读结束", progress)
            self.assertIn("POST /api/measures 200\n", progress)
            self.assertNotIn(question, progress)
            self.assertNotIn("不应大于4欧姆", progress)
            self.assertNotIn("雨天", progress)
            self.assertEqual(set(found), {"document", "reply", "evidence"})
            self.assertEqual(found["document"], "desk.docx")
            self.assertEqual(found["reply"], "示范答复：按打开的行处理，并见所引位置。")
            self.assertNotIn("不应大于4欧姆", found["reply"])
            self.assertNotIn("雨天", found["reply"])
            self.assertNotIn(question, found["reply"])
            evidence = found["evidence"]
            self.assertEqual(
                [item["kind"] for item in evidence],
                ["docx-cell", "docx-cell", "docx-paragraph"],
            )
            self.assertEqual(set(evidence[0]), {"document", "kind", "position", "text"})
            self.assertEqual(set(evidence[1]), {"document", "kind", "position", "text"})
            self.assertEqual(evidence[0]["text"], "雨天")
            self.assertIn("不应大于4欧姆", evidence[1]["text"])
            self.assertNotIn("label", evidence[0])
            self.assertEqual(evidence[2]["label"], "5.2")
            self.assertEqual(
                set(evidence[2]),
                {"document", "kind", "label", "position", "text"},
            )
            self.assertNotIn(question, evidence[2]["text"])
            empty = _post(
                base + "/api/measures",
                {
                    "situation": "",
                    "document": "desk.docx",
                    "document_tools": "docx",
                },
            )
            self.assertEqual(empty.status, 422)
            self.assertEqual(
                json.loads(empty.text)["error"],
                "regulation measures are unavailable",
            )
            long_question = "设" * 201
            too_long = _post(
                base + "/api/measures",
                {
                    "situation": long_question,
                    "document": "desk.docx",
                    "document_tools": "docx",
                },
            )
            self.assertEqual(too_long.status, 422)
            self.assertEqual(
                json.loads(too_long.text)["error"],
                "regulation measures are unavailable",
            )
            self.assertNotIn(long_question, too_long.text)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_docx(
                root / "desk.docx",
                (("4.1.2 接地限值", None), ("5.2 随后的复测。", None)),
                ((("雨天", "不应大于4欧姆。见5.2。"),),),
            )
            server = serve(root, research=ScriptedGridResearch(passage_lines=()))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.shutdown)
            self.addCleanup(server.server_close)
            base = f"http://127.0.0.1:{server.server_address[1]}"
            unread = "示范设备故障"
            missed = _post(
                base + "/api/measures",
                {
                    "situation": unread,
                    "document": "desk.docx",
                    "document_tools": "docx",
                },
            )
            self.assertEqual(missed.status, 422)
            self.assertEqual(
                json.loads(missed.text)["error"],
                "regulation measures are unavailable",
            )
            self.assertNotIn(unread, missed.text)
            self.assertNotIn("雨天", missed.text)

    def test_makefile_serves_the_desk_on_loopback(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(
            encoding="utf-8"
        )
        self.assertIn("\n.PHONY: dci-basic-example", makefile)
        self.assertIn(" grid-regulation\n", makefile)
        self.assertIn("\ngrid-regulation:\n", makefile)
        recipe = makefile.split("\ngrid-regulation:\n", 1)[1].split("\n", 1)[0]
        self.assertIn(
            "python -m asterion.applications.grid_regulation.page "
            '--corpus "$(GRID_CORPUS)" --port "$(GRID_PORT)"',
            recipe,
        )
        self.assertNotIn("--open", recipe)
        self.assertIn("GRID_CORPUS ?= $(CURDIR)/docs", makefile)
        self.assertIn("GRID_PORT ?= 8765", makefile)
        self.assertIn(
            "Grid regulation desk: grid-regulation (http://127.0.0.1:$(GRID_PORT)/",
            makefile,
        )
        self.assertNotIn("0.0.0.0", makefile[makefile.find("grid-regulation:") :])


def _get(url: str) -> _Body:
    return _open(urllib.request.Request(url))


def _post(url: str, payload: dict[str, str]) -> _Body:
    return _open(
        urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    )


def _open(request: urllib.request.Request) -> _Body:
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return _Body(response.status, response.headers, response.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return _Body(exc.code, exc.headers, exc.read().decode())
        finally:
            exc.close()
