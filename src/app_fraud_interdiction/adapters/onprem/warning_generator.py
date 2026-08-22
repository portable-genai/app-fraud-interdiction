"""On-prem WarningGeneratorPort: fail-fast portability placeholder (sovereign-exit proof).

Refusing is safe: the orchestrator falls back to the deterministic pack-template warning when the
generator raises, so an on-prem deployment with no bound model still interdicts, it just never
shows a model-drafted warning.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.warning import WarningRequest


class OnPremWarningGenerator:
    """Satisfies WarningGeneratorPort but refuses: the client wires its own model, or none."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, request: WarningRequest) -> str:
        raise NotImplementedError(
            "on-prem warning generation is a portability placeholder: bind the client's own "
            "model, or rely on the deterministic fallback (see docs/onprem-migration.md)"
        )
