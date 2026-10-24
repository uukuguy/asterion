from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from asterion.applications.grid_regulation.page import page_bytes, serve
from asterion.applications.grid_regulation.retrieve import write_demo_corpus


class _Body:
    def __init__(self, status: int, headers: object, text: str) -> None:
        self.status = status
        self.headers = headers
        self.text = text


class GridRegulationPageTests(unittest.TestCase):
    def test_page_is_one_local_file_and_cites_the_demo_clause(self) -> None:
        html = page_bytes().decode()
        self.assertIn("规程检索", html)
        self.assertIn("怎么填", html)
        self.assertIn("同一份文件", html)
        self.assertIn("查找原文位置", html)
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

    def test_makefile_serves_the_desk_on_loopback(self) -> None:
        makefile = (Path(__file__).resolve().parents[1] / "Makefile").read_text(
            encoding="utf-8"
        )
        self.assertIn("\n.PHONY: dci-basic-example", makefile)
        self.assertIn(" grid-regulation\n", makefile)
        self.assertIn("\ngrid-regulation:\n", makefile)
        self.assertIn(
            "python -m asterion.applications.grid_regulation.page "
            '--corpus "$(GRID_CORPUS)" --port "$(GRID_PORT)" --open',
            makefile,
        )
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
