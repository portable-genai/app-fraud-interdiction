"""WarningGeneratorPort: the one place a MODEL is allowed to touch an interdiction.

The generator drafts a locale-aware customer warning FROM the deterministic verdict and its cited
reasons. It owns no number and no verdict: the orchestrator validates every draft against the
engine's own output and discards it for a deterministic fallback on any failure, so an
interdiction never waits on generation and a model can never invent a figure or move a verdict.

The offline adapter is a deterministic, template-shaped generator that needs no model, so the
gate stays SDK-free; the managed adapter lazily imports the model SDK; the on-premises placeholder
fails fast. All three return a plain string, which the orchestrator then judges.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.warning import WarningRequest


@runtime_checkable
class WarningGeneratorPort(Protocol):
    def draft(self, request: WarningRequest) -> str:
        """Draft a customer warning for ``request``. The caller validates and may discard it."""
        ...
