"""Demonstration retrieval over grid-regulation PDF and DOCX files."""

from asterion.applications.grid_regulation.retrieve import (
    RegulationCitation,
    RegulationCitationError,
    RegulationMeasures,
    RegulationQuery,
    cite_regulation,
    lookup_measures,
    write_demo_corpus,
)

__all__ = (
    "RegulationCitation",
    "RegulationCitationError",
    "RegulationMeasures",
    "RegulationQuery",
    "cite_regulation",
    "lookup_measures",
    "write_demo_corpus",
)
