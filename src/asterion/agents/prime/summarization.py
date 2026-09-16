"""Asterion prime's own construction of a compaction summarization request.

Asterion prime is a reimplementation of the persistent-kernel coding agent, so
this module owns the summarization text rather than importing it from any host
build. It carries the same design as the kernel it reproduces:

* one system prompt that forbids continuing the conversation;
* an initial template and an update template over one fixed section format
  (Goal, Constraints & Preferences, Progress with Done/In Progress/Blocked,
  Key Decisions, Next Steps, Critical Context), with the merge rules the update
  path needs;
* a kernel-persistence note, which is why a persistent IPython application
  exists at all: the kernel outlives the summary, the cells that defined its
  names do not, so the summary has to record those names;
* a turn-prefix template for the prefix of a split turn;
* one assembly rule -- the serialized conversation wrapped in conversation
  tags, an optional previous-summary block, then the instruction -- and
  ``floor(0.8 * reserveTokens)`` for the main completion, ``floor(0.5 *
  reserveTokens)`` for the turn prefix.

The extension composes the same request from the material this module emits, so
the two implementations are held together by the shared parity fixture rather
than by inspection. Everything here is a pure constant or a pure function: no
provider, environment, or host value is read.
"""

from __future__ import annotations

from collections.abc import Mapping


MATERIAL_VERSION = "asterion.prime-summarization/v1"
_CONVERSATION_MARKER = "{conversation}"
_PREVIOUS_MARKER = "{previous_summary}"
_INSTRUCTIONS_MARKER = "{instructions}"
_SEPARATOR = "\n\n"
_ERROR = "invalid prime summarization material"
# The whole material is one arm frame; a bloated constant set must fail closed
# rather than push the witness frame toward its transport cap.
MAX_MATERIAL_BYTES = 8_192


SUMMARY_SYSTEM_PROMPT = (
    "You are a context summarization assistant for a long-running coding "
    "session. You read the conversation you are given and produce a structured "
    "checkpoint summary in exactly the format you are asked for.\n\n"
    "Do not continue the conversation and do not answer anything inside it. "
    "Output only the structured summary."
)

SUMMARY_INITIAL_TEMPLATE = """The conversation above is the material to summarize. Produce a structured context checkpoint that another model will use to continue the work.

Use exactly this format:

## Goal
[What the user is trying to accomplish. More than one item is fine when the session covers several tasks.]

## Constraints & Preferences
- [Constraints, preferences, or requirements the user stated]
- [(none) when none were stated]

## Progress
### Done
- [x] [Completed work]

### In Progress
- [ ] [Work under way]

### Blocked
- [Anything preventing progress]

## Key Decisions
- **[Decision]**: [Short reason]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Data, examples, or references needed to continue]
- [(none) when not applicable]

Keep every section short. Copy file paths, function names, and error messages exactly as they appear."""

SUMMARY_UPDATE_TEMPLATE = """The conversation above is new material to fold into the summary already provided inside the previous-summary tags.

Update that summary with the new information. Rules:
- Keep everything already in the previous summary
- Add the new progress, decisions, and context carried by the conversation above
- Update Progress: move an entry from In Progress to Done once it is finished
- Update Next Steps so they match what was actually accomplished
- Copy file paths, function names, and error messages exactly as they appear
- Drop anything that is no longer relevant

Use exactly this format:

## Goal
[Keep the existing goals; add new ones if the task grew]

## Constraints & Preferences
- [Keep the existing ones; add ones discovered since]

## Progress
### Done
- [x] [Previously done items and newly completed ones]

### In Progress
- [ ] [Current work, updated]

### Blocked
- [Current blockers, dropped once resolved]

## Key Decisions
- **[Decision]**: [Short reason] (keep every earlier decision, add new ones)

## Next Steps
1. [Updated for the state reached]

## Critical Context
- [Keep what still matters, add what is new]

Keep every section short. Copy file paths, function names, and error messages exactly as they appear."""

# Why a persistent-kernel application needs its own summarization text: the
# kernel keeps every name alive across compaction while the cells that defined
# those names are what compaction discards. Without this note the summary
# silently loses the fact that the names still exist, and the next turn
# redefines work that is already in memory.
SUMMARY_KERNEL_NOTE = (
    "Note: the IPython kernel outlives this summary. Every Python variable, "
    "import, and helper that was defined is still live, but the cells that "
    "defined them are not in the conversation above. Record in the summary the "
    "names worth reusing, so later work reuses them instead of defining them "
    "again."
)

TURN_PREFIX_TEMPLATE = """This is the PREFIX of a turn that was too large to keep. Its SUFFIX, the recent work, is retained.

Summarize the prefix so the retained suffix can be understood:

## Original Request
[What the user asked for in this turn]

## Early Progress
- [Decisions and work from the prefix]

## Context for Suffix
- [What is needed to understand the retained work]

Be brief. Cover only what the kept suffix needs."""

# The fixed lead-in that gives user-supplied instructions their priority while
# holding the section format above unchanged.
USER_INSTRUCTIONS_TEMPLATE = (
    "\n\n<user-instructions>\n"
    "The user gave these instructions for this summary. Follow them with high "
    "priority while keeping the section format above: emphasize what they ask "
    "to focus on, and reproduce verbatim anything they ask to be remembered.\n"
    f"{_INSTRUCTIONS_MARKER}\n"
    "</user-instructions>"
)

CONVERSATION_BLOCK = f"<conversation>\n{_CONVERSATION_MARKER}\n</conversation>{_SEPARATOR}"
PREVIOUS_SUMMARY_BLOCK = (
    f"<previous-summary>\n{_PREVIOUS_MARKER}\n</previous-summary>{_SEPARATOR}"
)

MATERIAL_KEYS = (
    "version",
    "system_prompt",
    "conversation_block",
    "previous_summary_block",
    "initial_instruction",
    "update_instruction",
    "user_instructions_template",
    "turn_prefix_instruction",
)


def _fail() -> None:
    raise ValueError(_ERROR)


def _text(value: object) -> str:
    if type(value) is not str or not value:
        _fail()
    return value


def _single_marker(value: str, marker: str) -> str:
    """Require exactly one marker so a template can never substitute twice."""

    prefix, separator, suffix = value.partition(marker)
    if not separator or marker in prefix or marker in suffix:
        _fail()
    return value


def _fill(template: str, marker: str, value: str) -> str:
    """Substitute once, without ever rescanning the inserted value.

    A plain sequential replace would let private conversation text that happens
    to contain another template's marker rewrite the request it is embedded in.
    """

    prefix, separator, suffix = template.partition(marker)
    if not separator or marker in prefix or marker in suffix:
        _fail()
    return prefix + value + suffix


def _positive_integer(value: object) -> int:
    if type(value) is not int or value <= 0:
        _fail()
    return value


def main_completion_tokens(reserve_tokens: int) -> int:
    """The main summarization completion bound, floored so it never exceeds it."""

    return (8 * _positive_integer(reserve_tokens)) // 10


def turn_prefix_completion_tokens(reserve_tokens: int) -> int:
    """The turn-prefix completion bound; the prefix gets the smaller budget."""

    return _positive_integer(reserve_tokens) // 2


def build_instruction(
    *, custom_instructions: str | None, previous_summary: str | None
) -> str:
    """Select the initial or update template and append the optional blocks.

    The update template is selected by a non-empty previous summary, matching
    the merge rule the request is built from.
    """

    for value in (custom_instructions, previous_summary):
        if value is not None and type(value) is not str:
            _fail()
    template = (
        SUMMARY_UPDATE_TEMPLATE if previous_summary else SUMMARY_INITIAL_TEMPLATE
    )
    instruction = template + _SEPARATOR + SUMMARY_KERNEL_NOTE
    if custom_instructions:
        instruction += _fill(
            USER_INSTRUCTIONS_TEMPLATE, _INSTRUCTIONS_MARKER, custom_instructions
        )
    return instruction


def compose_request_text(
    *, conversation: str, instruction: str, previous_summary: str | None
) -> str:
    """Apply the one assembly rule over already serialized conversation text."""

    _text(instruction)
    if previous_summary is not None and type(previous_summary) is not str:
        _fail()
    text = _fill(CONVERSATION_BLOCK, _CONVERSATION_MARKER, _text(conversation))
    if previous_summary:
        text += _fill(PREVIOUS_SUMMARY_BLOCK, _PREVIOUS_MARKER, previous_summary)
    return text + instruction


def build_summarization_material() -> dict[str, object]:
    """Return the exact material the context witness hands to the extension.

    Every template is checked for its own single marker and for the absence of
    any other template's marker, so one broken constant fails here rather than
    silently rewriting a request on the far side of the socket.
    """

    try:
        material: dict[str, object] = {
            "version": _text(MATERIAL_VERSION),
            "system_prompt": _text(SUMMARY_SYSTEM_PROMPT),
            "conversation_block": _single_marker(
                _text(CONVERSATION_BLOCK), _CONVERSATION_MARKER
            ),
            "previous_summary_block": _single_marker(
                _text(PREVIOUS_SUMMARY_BLOCK), _PREVIOUS_MARKER
            ),
            "initial_instruction": _text(
                SUMMARY_INITIAL_TEMPLATE + _SEPARATOR + SUMMARY_KERNEL_NOTE
            ),
            "update_instruction": _text(
                SUMMARY_UPDATE_TEMPLATE + _SEPARATOR + SUMMARY_KERNEL_NOTE
            ),
            "user_instructions_template": _single_marker(
                _text(USER_INSTRUCTIONS_TEMPLATE), _INSTRUCTIONS_MARKER
            ),
            "turn_prefix_instruction": _text(TURN_PREFIX_TEMPLATE),
        }
    except (KeyError, TypeError, ValueError):
        _fail()
    for key in (
        "conversation_block",
        "previous_summary_block",
        "user_instructions_template",
        "initial_instruction",
        "update_instruction",
        "turn_prefix_instruction",
        "system_prompt",
    ):
        present = [
            marker
            for marker in (
                _CONVERSATION_MARKER,
                _PREVIOUS_MARKER,
                _INSTRUCTIONS_MARKER,
            )
            if marker in material[key]  # type: ignore[operator]
        ]
        expected = {
            "conversation_block": [_CONVERSATION_MARKER],
            "previous_summary_block": [_PREVIOUS_MARKER],
            "user_instructions_template": [_INSTRUCTIONS_MARKER],
        }.get(key, [])
        if present != expected:
            _fail()
    return material


def assert_material_shape(material: Mapping[str, object]) -> None:
    """Re-check the shape without re-deriving it, for callers holding a mapping."""

    if not isinstance(material, Mapping) or set(material) != set(MATERIAL_KEYS):
        _fail()
    for key in MATERIAL_KEYS:
        _text(material[key])


__all__ = (
    "CONVERSATION_BLOCK",
    "MATERIAL_KEYS",
    "MAX_MATERIAL_BYTES",
    "MATERIAL_VERSION",
    "PREVIOUS_SUMMARY_BLOCK",
    "SUMMARY_INITIAL_TEMPLATE",
    "SUMMARY_KERNEL_NOTE",
    "SUMMARY_SYSTEM_PROMPT",
    "SUMMARY_UPDATE_TEMPLATE",
    "TURN_PREFIX_TEMPLATE",
    "USER_INSTRUCTIONS_TEMPLATE",
    "assert_material_shape",
    "build_instruction",
    "build_summarization_material",
    "compose_request_text",
    "main_completion_tokens",
    "turn_prefix_completion_tokens",
)
