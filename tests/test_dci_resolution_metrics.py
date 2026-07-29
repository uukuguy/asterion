"""Golden trajectory tests for DCI resolution evidence alignment."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from asterion.capabilities.dci.implementation.evaluation.resolution_metrics import (
    aggregate_dataset_localization,
    best_document_localization,
    compute_query_coverage,
    gold_document_set,
    query_localization,
    surfaced_gold_set,
)
from asterion.capabilities.dci.implementation.research.trajectory_resolution import (
    _GoldDocument,
    _ToolObservation,
    _align,
    _argument_fallbacks,
    _output_alignments,
    TrajectoryAnalysisConfig,
    TrajectoryResolutionError,
)


_FIXTURES = Path(__file__).parent / "fixtures" / "dci_trajectory"


def _fixture(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _documents(fixture: dict[str, object]) -> tuple[_GoldDocument, ...]:
    corpus = fixture["corpus"]
    assert type(corpus) is list
    documents = []
    for record in corpus:
        assert type(record) is dict
        body = record["body"]
        digest = record["sha256"]
        spans = record["evidence_spans"]
        assert type(body) is str and type(digest) is str and type(spans) is list
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == digest
        documents.append(
            _GoldDocument(
                document_id=record["document_id"],
                relative_path=record["relative_path"],
                body=body,
                digest=digest,
                evidence_spans=tuple((span["start"], span["end"]) for span in spans),
            )
        )
    return tuple(documents)


def _observation(fixture: dict[str, object]) -> _ToolObservation:
    call = fixture["tool_call"]
    assert type(call) is dict
    return _ToolObservation(
        call_id=call["call_id"],
        name=call["name"],
        arguments=call["arguments"],
        output=call["output"],
        external_digest="0" * 64,
    )


class TestDciTrajectoryResolutionFixtures(unittest.TestCase):
    def test_analysis_configuration_identifies_asterion_defined_parameters(self) -> None:
        config = TrajectoryAnalysisConfig(
            4096,
            read_minimum_evidence_overlap=0.75,
        )

        self.assertEqual(
            config.to_mapping(),
            {
                "parameter_source": "asterion-defined",
                "alignment_version": "dci.paper-alignment/v1",
                "read_minimum_evidence_overlap": 0.75,
                "segment_characters": 4096,
            },
        )
        with self.assertRaisesRegex(TrajectoryResolutionError, "configuration"):
            TrajectoryAnalysisConfig(
                4096,
                parameter_source="paper-reported",
            )

    def test_analysis_configuration_normalizes_integer_overlap_and_rejects_invalid_numbers(self) -> None:
        self.assertEqual(
            TrajectoryAnalysisConfig(
                4096,
                read_minimum_evidence_overlap=1,
            ).to_mapping()["read_minimum_evidence_overlap"],
            1.0,
        )
        for invalid in (True, 0, float("inf"), float("nan")):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(TrajectoryResolutionError, "configuration"):
                    TrajectoryAnalysisConfig(
                        4096,
                        read_minimum_evidence_overlap=invalid,
                    )

    def test_pipeline_outputs_are_verified_before_command_argument_fallback(self) -> None:
        for fixture_name in ("rg-head", "rg-rg"):
            with self.subTest(fixture=fixture_name):
                fixture = _fixture(fixture_name)
                documents = _documents(fixture)
                observation = _observation(fixture)

                alignments = _align(
                    (observation,), documents, TrajectoryAnalysisConfig(4096)
                )

                self.assertEqual([item["document_id"] for item in alignments], ["doc-a.txt"])
                self.assertEqual(_argument_fallbacks(observation, documents)[0]["document_id"], "doc-b.txt")
                self.assertEqual(alignments[0]["rule"], "grep-matched-line")

    def test_path_only_output_uses_verified_full_document_fallback(self) -> None:
        fixture = _fixture("path-only")
        documents = _documents(fixture)
        observation = _observation(fixture)

        alignments = _output_alignments(observation, documents)

        self.assertEqual([item["document_id"] for item in alignments], ["doc-a.txt"])
        self.assertEqual(alignments[0]["rule"], "full-document-fallback")
        self.assertEqual(alignments[0]["snippet_characters"], len(documents[0].body))
        self.assertEqual(_argument_fallbacks(observation, documents)[0]["document_id"], "doc-b.txt")

    def test_fixture_metrics_are_hand_calculated_from_verified_alignment(self) -> None:
        for fixture_name in ("rg-head", "rg-rg", "path-only"):
            with self.subTest(fixture=fixture_name):
                fixture = _fixture(fixture_name)
                expected = fixture["expected"]
                assert type(expected) is dict
                expected_coverage = expected["coverage"]
                expected_localization = expected["localization"]
                assert type(expected_coverage) is dict and type(expected_localization) is dict
                documents = _documents(fixture)
                alignments = _output_alignments(_observation(fixture), documents)
                surfaced_ids = tuple(sorted({item["document_id"] for item in alignments}))
                gold = gold_document_set(tuple(document.document_id for document in documents))
                coverage = compute_query_coverage(gold, surfaced_gold_set(gold, surfaced_ids))
                localizations = tuple(
                    best_document_localization(
                        document.document_id,
                        len(document.body),
                        [
                            item["snippet_characters"]
                            for item in alignments
                            if item["document_id"] == document.document_id
                        ],
                        fixture["configuration"]["segment_characters"],
                    )
                    for document in documents
                    if document.document_id in surfaced_ids
                )
                query = query_localization(localizations)
                dataset = aggregate_dataset_localization((query,))

                self.assertEqual(list(surfaced_ids), expected["surfaced_gold_ids"])
                self.assertEqual(coverage.any, expected_coverage["any"])
                self.assertEqual(coverage.mean, expected_coverage["mean"])
                self.assertEqual(coverage.all, expected_coverage["all"])
                self.assertEqual(
                    [(value.document_id, value.score) for value in query.per_document],
                    [(value["document_id"], value["value"]) for value in expected_localization["per_document"]],
                )
                self.assertEqual(query.value, expected_localization["query"]["value"])
                self.assertEqual(query.matched_gold_count, expected_localization["query"]["matched_gold_count"])
                self.assertEqual(dataset.value, expected_localization["dataset"]["value"])
                self.assertEqual(dataset.matched_gold_count, expected_localization["dataset"]["matched_gold_count"])

    def test_unknown_path_and_mismatched_line_text_are_ignored(self) -> None:
        fixture = _fixture("rg-head")
        observation = _observation(fixture)
        invalid_output = _ToolObservation(
            call_id=observation.call_id,
            name=observation.name,
            arguments={"command": "rg -n gold unknown-token.txt"},
            output="unknown.txt:3:gold text\ndoc-a.txt:3:not gold text\n",
            external_digest=observation.external_digest,
        )

        self.assertEqual(_output_alignments(invalid_output, _documents(fixture)), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
