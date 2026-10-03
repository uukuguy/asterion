"""Operator console logging defaults for Prime's native integrations."""

from __future__ import annotations

import logging


def configure_console_logging() -> None:
    """Keep third-party scorecard setup noise out of interactive runs."""

    logger = logging.getLogger("arc_agi.scorecard")
    logger.setLevel(logging.WARNING)
    logger.disabled = True


# Configure before the Prime provider imports any optional ARC SDK modules.
configure_console_logging()
