"""Logging that never writes uploaded content (deck text, contact details) to logs."""

from __future__ import annotations

import logging

_CONFIGURED = False


def get_logger(name: str) -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        from app.config import get_settings

        logging.basicConfig(level=get_settings().im_log_level.upper(),
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        _CONFIGURED = True
    return logging.getLogger(name)
