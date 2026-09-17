"""The one fixed P2 long-context task and the bounds the witness requires.

The corpus lives behind the injected ``prime.p2-oracle`` service; the task
statement is the only prompt-side content the model sees. Source material
must never enter the prompt or worker state.
"""

from __future__ import annotations

P2_TASK_STATEMENT = (
    "Use the injected prime.p2-oracle service to retrieve at least one bounded "
    "record from the operator-owned corpus, transform it if needed, and emit the "
    "canonical answer the answer oracle accepts. The corpus path, record bounds "
    "and oracle method are supplied by the injected service, not by you."
)

# One bounded retrieval/transform round-trip, in the natural units of the
# corpus. the witness uses (offset=0, length=1); tighter bounds would still
# satisfy the spec but the regression tests assert exactly this tuple.
P2_RETRIEVAL_BOUNDS: tuple[int, int] = (0, 1)