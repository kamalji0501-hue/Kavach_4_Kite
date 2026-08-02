"""Logging handler that records ERROR+ to domain incident tracker."""

from __future__ import annotations

import logging
from pathlib import Path

from core.incident_tracker import record_from_log_record


class DomainIncidentHandler(logging.Handler):
    """Attach once per bot process to capture errors into by_domain incident files."""

    def __init__(self, workspace_root: Path, domain: str) -> None:
        super().__init__(level=logging.ERROR)
        self._workspace_root = workspace_root
        self._domain = domain.lower()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            record_from_log_record(self._workspace_root, self._domain, record)
        except Exception:
            self.handleError(record)
