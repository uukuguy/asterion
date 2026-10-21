"""Run native.dci-research through the standard Native entry."""

from __future__ import annotations

from collections.abc import Mapping

from asterion.agents.native.application import (
    NativeApplicationSpec,
    NativeOperatorContext,
    prepare_native_application,
)
from asterion.runner.application import ApplicationRunResult
from asterion.runtime.factory import RuntimeFactoryRegistry


QUESTION = (
    "Answer the following question using only wiki_dump.jsonl in the current "
    "directory. Do not use web search. Use rg instead of grep for fast "
    "searching. Question: In which street did the Great Fire of London originate?"
)


async def run_native_dci_research(
    *,
    runtime_factories: RuntimeFactoryRegistry,
    runtime_options: Mapping[str, str],
    corpus_root: str,
    question: str,
    run_id: str,
) -> ApplicationRunResult:
    """Prepare and run one DCI retrieval. The caller owns the registry."""

    application = prepare_native_application(
        NativeApplicationSpec(
            application_id="native.dci-research",
            application_version="1.0.0",
        ),
        NativeOperatorContext(
            runtime_factories=runtime_factories,
            runtime_options=runtime_options,
            host_service_options={
                "corpus.local-root": {"root": corpus_root},
            },
            managed_host_services={},
        ),
    )
    return await application.run(question, run_id=run_id)
