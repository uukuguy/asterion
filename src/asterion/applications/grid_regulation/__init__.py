"""Demonstration retrieval over grid-regulation PDF and DOCX files."""

from asterion.applications.grid_regulation.retrieve import (
    RegulationCitation,
    RegulationCitationError,
    RegulationQuery,
    cite_regulation,
    write_demo_corpus,
)

__all__ = (
    "RegulationCitation",
    "RegulationCitationError",
    "RegulationQuery",
    "cite_regulation",
    "write_demo_corpus",
)
