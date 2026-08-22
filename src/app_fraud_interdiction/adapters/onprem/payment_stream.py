"""On-prem PaymentStreamPort: fail-fast portability placeholder (the sovereign-exit proof)."""

from __future__ import annotations

from ...config import Settings
from ...domain.models import PaymentEvent
from ...ports.payment_stream import StreamRequest


class OnPremPaymentStream:
    """Satisfies PaymentStreamPort but refuses: the client wires its own payment bus."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def poll(self, request: StreamRequest) -> tuple[PaymentEvent, ...]:
        raise NotImplementedError(
            "on-prem payment intake is a portability placeholder: bind the client's own "
            "in-flight payment bus (see docs/onprem-migration.md)"
        )
