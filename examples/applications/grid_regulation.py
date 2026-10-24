"""Provider-free citation demo for fictional grid-regulation documents.

The operator desk is the single file `page.html`. `make grid-regulation`
serves it on localhost. This demo does not start Pi and does not call a model.
"""

import asyncio
import json
import tempfile
from pathlib import Path

from asterion.applications.grid_regulation import (
    RegulationQuery,
    cite_regulation,
    write_demo_corpus,
)


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write_demo_corpus(root)
        citation = await cite_regulation(
            root,
            RegulationQuery(
                clause_id="4.1.2",
                version="DL/T 9000-2024",
                finding="不应大于4欧姆",
            ),
            document_tools="docx,pdf",
        )
    print(
        json.dumps(
            {
                "clause_id": citation.clause_id,
                "version": citation.version,
                "calls": list(citation.calls),
                "anchors": list(citation.anchors),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
