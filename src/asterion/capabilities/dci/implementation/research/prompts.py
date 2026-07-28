"""Exact, source-bound prompt contracts for DCI benchmark execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from asterion.capabilities.dci.implementation.runtime.pi_rpc import (
    FINAL_ANSWER_RECOVERY_PROMPT,
)


PAPER_REFERENCE_PROMPT_CONTRACT = "dci.paper-prompt/arxiv:2605.05242v1/v1"
_UPSTREAM_COMMIT = "271f37e71f053bf0c99c05ce6d2fb53b841d922e"
UPSTREAM_GITHUB_PROMPT_CONTRACT = f"dci.upstream-github-prompt/{_UPSTREAM_COMMIT}/v1"
ASTERION_SAFE_PROMPT_CONTRACT = "asterion.dci.prompt/safe/v1"
_CANONICAL_QUERY = "__DCI_QUERY__"
_CANONICAL_CORPUS = Path("/__dci_prompt_contract_corpus__")
_CANONICAL_HINT = "__DCI_CORPUS_HINT__"


class PromptContractError(ValueError):
    """Safe public error for unknown or unsupported DCI prompt contracts."""


@dataclass(frozen=True, slots=True)
class PromptContract:
    """One immutable source-family prompt contract without public prompt bodies."""

    contract_id: str
    source_family: str
    qa_builder: Callable[[str, Path], str]
    ir_builder: Callable[[str, Path, str | None], str]
    final_answer_recovery: str | None


def _paper_qa(query: str, corpus_dir: Path) -> str:
    return (
        "DCI-Agent Prompt\n\n"
        f"You are a careful research assistant. Answer the question below using ONLY documents in {corpus_dir}.\n"
        "Do not use online search or any external tools beyond ripgrep and Bash.\n\n"
        f"Question: {query}\n\n"
        "SEARCH STRATEGY (follow exactly):\n"
        "1. Search directly using ripgrep/Bash — do NOT use the Agent tool, spawn subagents, or browse the web.\n"
        "2. Run multiple ripgrep/Bash searches IN PARALLEL within a single response to save time.\n"
        "3. Use diverse, targeted keywords to maximize recall before drawing conclusions.\n\n"
        "INSTRUCTIONS:\n"
        f"• Search {corpus_dir} thoroughly with multiple relevant keyword combinations.\n"
        "• Identify and rule out competing candidate answers before committing to one.\n"
        f"• Cite every supporting finding inline using the document's path, e.g. [{corpus_dir}/relative_path].\n\n"
        "Your response MUST follow this exact format:\n\n"
        f"Explanation: {{{{step-by-step reasoning with inline, e.g. [{corpus_dir}/relative_path]}}}}\n"
        "Exact Answer: {{concise final answer only}}\n"
        "Confidence: {{0–100%; use below 50% if evidence is weak, ambiguous, or missing}}\n"
    )


def _upstream_qa(query: str, corpus_dir: Path) -> str:
    return (
        "Answer the following question. "
        f"The answer is contained in the corpus directory at @{corpus_dir}. "
        "**Do Not use web search!** Use ripgrep (rg) instead of grep for fast searching.\n\n"
        "QUESTION:\n"
        f"{query}\n"
    )


def _safe_qa(query: str, corpus_dir: Path) -> str:
    return (
        "Answer the following question. "
        f"The answer is contained in the corpus directory at @{corpus_dir}. "
        "**Do Not use web search!** Use ripgrep (rg) instead of grep for fast searching. "
        "After using tools, always finish with a non-empty textual final answer.\n\n"
        "QUESTION:\n"
        f"{query}\n"
    )


def _upstream_ir(query: str, corpus_dir: Path, corpus_hint: str | None) -> str:
    corpus_hint_section = (
        f"CORPUS STRUCTURE:\n{corpus_hint}\n\n" if corpus_hint else ""
    )
    return (
        f"You are a careful research assistant. Answer the question below using ONLY documents in @{corpus_dir}.\n"
        "Do not use online search or any external tools beyond Grep and Bash.\n\n"
        f"Question:\n{query}\n\n"
        f"{corpus_hint_section}"
        "SEARCH STRATEGY (follow exactly):\n"
        "1. Use Grep/Bash ONLY — do NOT use the Agent tool, spawn subagents, or browse the web.\n"
        "2. Run multiple Grep/Bash searches IN PARALLEL within a single response to save time.\n"
        "3. Use diverse, targeted keywords to maximize recall before drawing conclusions.\n"
        "4. After each round, reflect on gaps and launch follow-up searches to cover missing angles.\n"
        "5. Do NOT stop after finding a few documents — exhaust all plausible search angles.\n\n"
        "RETRIEVAL INSTRUCTIONS:\n"
        "- Both recall AND precision matter equally — the output is evaluated with NDCG, which penalizes both missing relevant documents and including irrelevant ones.\n"
        "- Find EVERY document that is genuinely relevant. Missing a gold document hurts recall.\n"
        "- Read each candidate document carefully before including it. Including an irrelevant document hurts precision.\n"
        "- A document is relevant only if it directly addresses the question or provides essential supporting evidence for the answer. Do NOT include tangential or loosely related documents.\n\n"
        "RANKING INSTRUCTIONS:\n"
        "- Rank the final list by relevance: the most directly useful document for answering the question goes first. Ranking quality affects NDCG score.\n\n"
        "Your response MUST follow this exact format:\n"
        "Relevant Documents (ranked by relevance, most relevant first; maximum 20):\n"
        "1. {corpus}/path/to/doc1.txt\n"
        "2. {corpus}/path/to/doc2.txt\n"
        "3. {corpus}/path/to/doc3.txt\n"
        "(use full relative paths from the working directory; list at most 20 documents; omit any document that is not directly relevant)\n\n"
        "Explanation: {step-by-step reasoning with inline citations, e.g. [{corpus}/relative_path]}\n"
        "Exact Answer: {concise final answer only}\n"
        "Confidence: {0–100%; use below 50% if evidence is weak, ambiguous, or missing}\n"
    )


def _unreported_ir(
    _query: str, _corpus_dir: Path, _corpus_hint: str | None
) -> str:
    raise PromptContractError("DCI prompt contract does not report this prompt kind")


PROMPT_CONTRACTS: Mapping[str, PromptContract] = MappingProxyType(
    {
        ASTERION_SAFE_PROMPT_CONTRACT: PromptContract(
            contract_id=ASTERION_SAFE_PROMPT_CONTRACT,
            source_family="asterion-safe",
            qa_builder=_safe_qa,
            ir_builder=_upstream_ir,
            final_answer_recovery=FINAL_ANSWER_RECOVERY_PROMPT,
        ),
        PAPER_REFERENCE_PROMPT_CONTRACT: PromptContract(
            contract_id=PAPER_REFERENCE_PROMPT_CONTRACT,
            source_family="paper-reference",
            qa_builder=_paper_qa,
            ir_builder=_unreported_ir,
            final_answer_recovery=None,
        ),
        UPSTREAM_GITHUB_PROMPT_CONTRACT: PromptContract(
            contract_id=UPSTREAM_GITHUB_PROMPT_CONTRACT,
            source_family="upstream-github",
            qa_builder=_upstream_qa,
            ir_builder=_upstream_ir,
            final_answer_recovery=None,
        ),
    }
)


def resolve_prompt_contract(contract_id: object) -> PromptContract:
    """Resolve one declared prompt contract without revealing its body."""

    if type(contract_id) is not str or contract_id not in PROMPT_CONTRACTS:
        raise PromptContractError("DCI prompt contract is invalid")
    return PROMPT_CONTRACTS[contract_id]


def prompt_contract_sha256(contract: PromptContract, prompt_kind: str) -> str:
    """Return the canonical body-free identity for one contract prompt kind."""

    if prompt_kind == "qa":
        body = contract.qa_builder(_CANONICAL_QUERY, _CANONICAL_CORPUS)
    elif prompt_kind == "ir":
        body = contract.ir_builder(
            _CANONICAL_QUERY, _CANONICAL_CORPUS, _CANONICAL_HINT
        )
    else:
        raise PromptContractError("DCI prompt contract does not report this prompt kind")
    return hashlib.sha256(
        (
            json.dumps(
            {
                "source_family": contract.source_family,
                "prompt_kind": prompt_kind,
                "body": body,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "ASTERION_SAFE_PROMPT_CONTRACT",
    "PAPER_REFERENCE_PROMPT_CONTRACT",
    "PROMPT_CONTRACTS",
    "PromptContract",
    "PromptContractError",
    "UPSTREAM_GITHUB_PROMPT_CONTRACT",
    "prompt_contract_sha256",
    "resolve_prompt_contract",
]
