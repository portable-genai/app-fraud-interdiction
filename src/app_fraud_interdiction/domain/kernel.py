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


# --------------------------------------------------------------------------- #
# Safety (guardrail): the A1 Guardrail Gateway concerns, vertical-neutral (rule R1)
# --------------------------------------------------------------------------- #
class Direction(LenientStrEnum):
    """Which leg of a generation call a guardrail screen covers."""

    INPUT = "input"
    OUTPUT = "output"


class GuardrailCategory(LenientStrEnum):
    """What kind of thing a guardrail finding names. A fork adds to this; it never removes."""

    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SENSITIVE_DATA = "sensitive_data"
    MALICIOUS_URL = "malicious_url"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class GuardrailFinding:
    """One thing a guardrail screen noticed, never the whole verdict on its own."""

    category: GuardrailCategory
    confidence: str  # "low" | "medium" | "high"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    """What a guardrail screen decided about one direction of one generation call.

    ``sanitized_text`` is the text to use going forward when ``allowed`` is True: it may equal
    the input unchanged, and it may be SHORTER or EMPTY when the screen redacted it, and the
    caller uses it exactly as given, never falling back to the unscreened original. It is
    ``None`` when the call is blocked, because a blocked call has no safe text to substitute.
    Both halves are enforced at construction, so a verdict that is allowed with no text (or
    blocked with some) cannot exist for a caller to misread.
    """

    allowed: bool
    direction: Direction
    findings: tuple[GuardrailFinding, ...] = ()
    sanitized_text: str | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.allowed and self.sanitized_text is None:
            raise ValueError(
                "an allowed GuardrailVerdict must carry the text to use going forward "
                "(sanitized_text, the input unchanged when nothing was redacted)"
            )
        if not self.allowed and self.sanitized_text is not None:
            raise ValueError("a blocked GuardrailVerdict carries no sanitized_text")


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
