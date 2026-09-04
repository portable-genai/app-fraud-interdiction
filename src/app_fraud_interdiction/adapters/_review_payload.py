"""Shared conversion from an escalated result to an ``review-kit`` Review payload.

Lives in the adapter layer, not the pure domain, because it depends on the kit. The subject, summary
and every citation snippet are redacted BEFORE they leave the process (the same
redact-before-anything rule the audit write obeys), using the shared ``pii-kit``, so no raw
identifier reaches human-review-console over the wire; human-review-console redacts again before its
own audit write (defence in depth). ``maker`` and ``tenant`` are asserted here and trusted by
human-review-console because the caller is an authenticated S2S service; per-hop on-behalf-of token
exchange is the deferred next layer.
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.kernel import Verdict
from ..domain.models import InterdictionAssessment

#: Cap the citations carried on the wire: enough for a reviewer to trace the decision without
#: copying the whole evidence set into the console.
_MAX_CITATIONS = 8

#: The console is a SHARED sink: a case filed in one market may still quote another market's
#: national id, so the payload is scrubbed against every jurisdiction's rows plus the universal
#: email/phone rows, whatever this deployment's own ``domain.pii.JURISDICTIONS`` selects.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

#: Verdicts that demand dual control (two approvals) rather than a single checker. A BLOCK stops
#: a customer's money, so releasing it is a two-person decision.
_DUAL_CONTROL = (Verdict.BLOCK,)


def _redact(text: str) -> str:
    """Mask every jurisdiction's identifiers plus email/phone, and normalise whitespace."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _kit_citations(result: InterdictionAssessment) -> tuple[KitCitation, ...]:
    """Mask EVERY field, not only the snippet.

    Today's citations are rule-pack locators with nothing to mask, and that is exactly why this
    is unconditional, for the same reason the event id above is masked unconditionally: the
    console is a shared sink, no sink can tell a pack locator from a citation cut out of caller
    text by inspection, and masking text that carries no identifier is a no-op. The dedupe key is
    the masked id, so two rows differing only inside a masked span collapse to one.
    """
    seen: set[str] = set()
    out: list[KitCitation] = []
    for citation in result.citations:
        source_id = _redact(citation.source_id)
        if source_id in seen:
            continue
        seen.add(source_id)
        out.append(
            KitCitation(
                source_id=source_id,
                title=_redact(citation.title),
                snippet=_redact(citation.snippet),
            )
        )
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def result_to_review(result: InterdictionAssessment, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when an interdiction escalates.

    The event id is an internal reference and normally carries no personal data, but the console
    is a shared sink and the redact-before-anything rule is unconditional: the id is masked before
    it is used for the subject, the case reference OR the idempotency key, so no field on the wire
    can leak a raw identifier. Masking is deterministic, so a normal (identifier-free) id is
    unchanged and the idempotency key stays stable.
    """
    safe_event_id = _redact(result.event_id)
    return Review(
        action="app_fraud_interdiction:interdict",
        subject=safe_event_id,
        maker=maker,
        tenant=tenant,
        summary=_redact(result.summary),
        severity=result.band.value,
        required_approvals=2 if result.verdict in _DUAL_CONTROL else 1,
        sod_group="app_fraud_interdiction-maker-checker",
        case_ref=safe_event_id,
        # Producer-owned, tenant-scoped key so a retried delivery is idempotent at the console.
        source_key=f"app-fraud-interdiction:{safe_event_id}:{result.verdict.value}",
        citations=_kit_citations(result),
    )
