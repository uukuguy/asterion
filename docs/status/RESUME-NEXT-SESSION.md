# Live Session Checkpoint

> Updated: 2026-10-24 16:49. **Session remains active — not a final handoff.**

## TL;DR

- Framework document tools are optional. Empty configuration keeps plain-text `read`, `grep`, and `bash`. `docx`, `pdf`, and `docx,pdf` add citation anchors.
- The grid-regulation demo cites one fictional clause from a DOCX or PDF span and records the anchor through `dci.research`. It does not start Pi and does not call a model.
- `dci-agent-lite` is still the in-repo product provider. Do not run `make native-dci-example`.

## Verified facts

- `search_documents` returns public anchors only: corpus-relative document, source sha256, kind, position, and span sha256. `read_span` re-reads the span for the caller. Absolute paths, `..`, and symlinks fail closed.
- DOCX anchors are body paragraphs, with numbering level and id when `w:numPr` is present, or table cells. PDF anchors are page, item, x, and y for FlateDecode content streams whose text is UTF-16 hex or a literal string.
- `document-read` in a research stream verifies the anchor against the corpus. The locations artifact gains `anchors`. Plain `read` and `grep` streams still have only `paths`.
- `uv run python -m unittest tests.test_document_tools tests.test_grid_regulation tests.test_dci_research_capability tests.test_native_application` passed: 27 tests. Ruff check passed on the edited Python files.
- `examples/applications/grid_regulation.py` exits 0 and prints the `4.1.2` anchor for `grounding.docx`. The fictional corpus is `DL/T 9000-2024`. Span text is not in the output.
- The shipped native retrieval preset still launches `read,grep`.

## Current judgment

- The demo shows the citation contract on documents this writer can round-trip. It does not show a live model choosing tools, and it does not read arbitrary enterprise PDFs that use CID fonts or scanned images.
- Removing `dci-agent-lite` remains a separate change. `native.dci-complete@1.0.0` is still not built.

## Historical archive

- Do not remove `--mode rpc`. Do not return the one-shot stdout line cap to 64KB.
- Do not rewrite the paper ablation row name `dci-agent-lite`.
- Do not move `level0`–`level4`, the ablation matrix, judges, or dataset targets onto the public runtime.
- D-2026-07-31-02 remains active. A full dataset run still needs its own authorization.

## Open boundary

- CID-font PDFs, scanned pages, text boxes, and headers are not citation anchors yet.
- The grid demo is not registered on provider `native` and does not satisfy the shipped preset's missing `shell` advertisement.
- Claude's static manifest still advertises `shell` when the launched tools are Read, Grep, and Glob.
- `make promotion-check` has not been run since `context-policy-extension.mjs` was added. This change does not alter that extension.
- Worktrees `asterion-p1-workload`, `asterion-p2-worker`, and `asterion-p3-real-rlm` remain. They are unrelated.

## Next action

1. Keep document tools opt-in. Extend the PDF reader only when a real regulation file is in scope.
2. Remove provider `dci-agent-lite` as its own change. Keep command `asterion-dci`. Leave the paper ablation row name unchanged.
3. Do not run `make native-dci-example` or any dataset or model call.

## Ready-to-paste command

```bash
uv run python -m unittest tests.test_document_tools tests.test_grid_regulation tests.test_dci_research_capability
```
