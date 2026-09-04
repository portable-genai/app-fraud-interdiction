"""Vertical-neutral domain kernel: pure-stdlib types the interdiction engine reasons over.

Taxonomies are ``StrEnum``s from the commons (a member IS its wire value), citations carry
provenance, and the WORM audit record is stored already-redacted. Nothing here imports a web
framework or a cloud SDK (the commons packages it uses are themselves stdlib).

Two taxonomies drive every consequential decision, and they are deliberately separate:

* :class:`RiskBand` is the SCORE band, a coarse summary of how much risk the deterministic engine
  found. It is advisory to a human and never, by itself, stops a payment.
* :class:`Verdict` is the ACTION the engine ordered on an in-flight payment. ``HOLD`` and
  ``BLOCK`` are consequential and are engine verdicts only: a model may narrate one, never move
  one. Keeping the action separate from the band means the thresholds that turn a score into a
  stop are policy the engine owns, not a label a narration can nudge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from hex_service_kit.enums import LenientStrEnum


def utcnow() -> datetime:
    """Timezone-aware UTC now (the single wall-clock the surfaces use for audit timestamps).

    The deterministic engine never calls this: it takes ``as_of`` (the payment's event time)
    from the caller, so a replay of the same event produces the same verdict regardless of when
    it runs. Only the audit sink, which records when a decision was TAKEN, reads the clock.
    """
    return datetime.now(UTC)


class RiskBand(LenientStrEnum):
    """How much risk the engine's score represents. Advisory; never a stop on its own."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Verdict(LenientStrEnum):
    """The action the deterministic engine ordered on an in-flight payment.

    Ordered from least to most restrictive. ``HOLD`` and ``BLOCK`` are consequential: they set
    ``requires_human_review`` and route to the human-review-console (rule R8), and no model can
    produce
    or change them.
    """

    ALLOW = "allow"
    WARN = "warn"
    HOLD = "hold"
    BLOCK = "block"


#: The verdicts that stop or delay a payment and therefore demand a human. A frozenset so it is a
#: constant-time membership test the orchestrator and the surfaces share one definition of.
CONSEQUENTIAL_VERDICTS: frozenset[Verdict] = frozenset({Verdict.HOLD, Verdict.BLOCK})


@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to a generated claim or a fired rule (source + optional locator)."""

    source_id: str
    title: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, already-redacted record of one interdiction decision (P-04 / rule R2)."""

    action: str
    actor: str
    verdict: Verdict
    band: RiskBand
    redacted_summary: str
    citations: tuple[Citation, ...] = ()
    timestamp: datetime = field(default_factory=utcnow)
