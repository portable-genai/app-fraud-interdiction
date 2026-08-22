"""Managed PaymentStreamPort: pull in-flight payments from BigQuery streaming features.

The SDK import is LAZY (inside the method), so this module imports with no cloud SDK present and
the offline gate can bind it; called with nothing reachable it fails on that import, which is the
honest managed refusal (never a silent empty batch that would look like "no risky payments").
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import PaymentEvent
from ...ports.payment_stream import StreamRequest


class BigQueryPaymentStream:
    """Read in-flight payment events from a BigQuery streaming feature table (managed profile)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def poll(self, request: StreamRequest) -> tuple[PaymentEvent, ...]:
        from google.cloud import bigquery  # noqa: F401  (lazy: proves managed reachability)

        raise NotImplementedError(  # pragma: no cover - needs a live BigQuery project
            "BigQueryPaymentStream needs a configured BigQuery project and dataset; "
            "see docs/runbook.md"
        )
