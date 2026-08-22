"""Local PaymentStreamPort: a scripted, deterministic in-flight payment stream (no BigQuery).

Replays the fixture payments in ``_fixture_data`` in a fixed order, so the offline gate, the demo
and the eval all pull the same events. A scripted stream is not a no-op: it exercises the real
intake path (batch, market filter, cap) that the managed BigQuery adapter implements against a
streaming feature table.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import PaymentEvent
from ...ports.payment_stream import StreamRequest
from . import _fixture_data


class LocalPaymentStream:
    """Serve the scripted fixture payments for the SDK-free ``local`` profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def poll(self, request: StreamRequest) -> tuple[PaymentEvent, ...]:
        return _fixture_data.events_for(request.market, request.max_events)
