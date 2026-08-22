"""PaymentStreamPort: the inbound edge for in-flight payment and checkout events.

The intake is a stream: an adapter pulls the next batch of in-flight payments (BigQuery streaming
features in the cloud, a scripted deterministic stream offline, a fail-fast placeholder on
premises). The port returns raw cited events and computes nothing: scoring is the engine's job,
downstream of here, so a swapped stream adapter can never change a verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..domain.models import PaymentEvent


@dataclass(frozen=True, slots=True)
class StreamRequest:
    """What to pull from the stream: a market filter and a batch cap, both optional."""

    market: str = ""
    max_events: int = 100


@runtime_checkable
class PaymentStreamPort(Protocol):
    def poll(self, request: StreamRequest) -> tuple[PaymentEvent, ...]:
        """Return the next batch of in-flight payment events, oldest event-time first."""
        ...
