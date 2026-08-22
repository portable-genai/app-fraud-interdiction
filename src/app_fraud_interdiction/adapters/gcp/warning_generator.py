"""Managed WarningGeneratorPort: draft the customer warning with the managed model (lazy import).

The orchestrator still validates and may discard whatever this returns: the model is the one seam
where narration is drafted, never where a verdict or a figure is decided. The SDK import is lazy,
so this binds offline and refuses on the import when the model is unreachable.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.warning import WarningRequest


class VertexWarningGenerator:
    """Draft a customer warning with the managed generative model (managed profile)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, request: WarningRequest) -> str:
        from google import genai  # noqa: F401  (lazy: proves managed reachability)

        raise NotImplementedError(  # pragma: no cover - needs a live model endpoint
            "VertexWarningGenerator needs a configured model endpoint; see docs/runbook.md"
        )
