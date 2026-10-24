"""Domain-neutral document tools. Plain text stays on the runtime's own tools."""

from asterion.documents.docx import write_docx
from asterion.documents.pdf import write_pdf
from asterion.documents.tools import (
    DocumentToolError,
    parse_document_tools,
    read_span,
    search_documents,
    verify_public_anchor,
)

__all__ = (
    "DocumentToolError",
    "parse_document_tools",
    "read_span",
    "search_documents",
    "verify_public_anchor",
    "write_docx",
    "write_pdf",
)
