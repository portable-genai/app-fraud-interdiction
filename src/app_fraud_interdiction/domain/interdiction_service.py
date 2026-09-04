"""The interdiction orchestrator: deterministic verdict, grounded warning, redact-before-audit.

This is the pure-stdlib heart of the vertical. It pulls cited features for a payment, runs the
deterministic engine (whose verdict a model can never move), optionally folds in scam-cue hits from
a linked call, drafts a customer warning through the one model seam, VALIDATES that draft against
the engine's own output and discards it for a deterministic fallback on any failure, then redacts
and writes a WORM audit record. It routes nothing itself: rule R8 routing to the
human-review-console is the surfaces' job, so the same escalation is routed once, on whichever
surface produced it (``api/app.py``, ``cli/main.py``, ``agent/tools.py``).

Everything here is injected as a port Protocol or a pure value, so nothing in this module imports
a web framework, a cloud SDK or a YAML parser: the packs and the lexicon are handed in already
parsed.
"""

from __future__ import annotations

from collections.abc import Mapping

from pii_kit import redact
from speech_lexicon_kit import Lexicon

from ..ports.audit import AuditSinkPort
from ..ports.conversation_channel import ConversationChannelPort
from ..ports.features import FeaturePort
from ..ports.observability import ObservabilityTracerPort
from ..ports.warning_generator import WarningGeneratorPort
from . import scam_lexicon
from .interdiction_engine import assess as engine_assess
from .kernel import AuditEvent, Citation, utcnow
from .models import FeatureValue, FeatureVector, InterdictionAssessment, PaymentEvent
from .pii import PII_PATTERNS
from .rulepack import RulePack
from .warning import WarningRequest, build_fallback_warning, figures_in, validate_warning

_WARNING_SOURCE_MODEL = "model"
_WARNING_SOURCE_FALLBACK = "fallback"

#: One span per assessed payment. Structural attributes only: see
#: :meth:`InterdictionService.assess`.
_ASSESS_SPAN = "interdiction.assess"


class InterdictionService:
    """Score one in-flight payment and produce a cited, audited interdiction assessment."""

    def __init__(
        self,
        *,
        features: FeaturePort,
        warning_generator: WarningGeneratorPort,
        audit: AuditSinkPort,
        tracer: ObservabilityTracerPort,
        packs: Mapping[str, RulePack],
        lexicon: Lexicon,
        conversation_channel: ConversationChannelPort | None = None,
    ) -> None:
        self._features = features
        self._warning_generator = warning_generator
        self._audit = audit
        self._tracer = tracer
        self._packs = packs
        self._lexicon = lexicon
        self._conversation_channel = conversation_channel

    def assess(
        self, event: PaymentEvent, *, actor: str, tenant: str = ""
    ) -> InterdictionAssessment:
        """Score one in-flight payment end to end, inside one span.

        ``tenant`` is the VERIFIED principal's, never a value from a request body, and it scopes
        the ONE read this service makes of stored data: the linked call, which the caller names
        by a client-supplied ``call_ref`` and which is a recording of somebody else's customer.
        An empty tenant resolves no call rather than any call.

        The span's attributes are STRUCTURAL only: the action, the actor and the market whose
        rule pack was applied. Never the payer or payee reference, never the event id, never the
        customer's memo and never the drafted warning. A trace backend is not the WORM audit
        trail: it has no redaction stage, a wider read audience and no retention rule written
        against a regulator's requirement, so anything content-shaped that reaches a span has
        left the boundary the redact-before-audit call exists to hold, and left it silently.
        """
        with self._tracer.span(
            _ASSESS_SPAN,
            action="assess",
            actor=actor,
            market=event.market,
        ):
            pack = self._pack_for(event.market)
            features = self._enriched_features(event, tenant)
            verdict = engine_assess(event, features, pack)

            warning, source = self._warning(event, verdict, pack)
            assessment = InterdictionAssessment(
                event_id=event.event_id,
                market=event.market,
                as_of=event.as_of,
                verdict=verdict.verdict,
                score=verdict.score,
                band=verdict.band,
                reason_codes=verdict.reason_codes,
                warning=warning,
                warning_source=source,
                requires_human_review=verdict.requires_human_review,
                signal_key=verdict.signal_key,
                citations=verdict.citations,
            )

            # Redact BEFORE the audit write: no raw identifier or memo reaches the WORM record.
            self._audit.record(
                AuditEvent(
                    action="interdict",
                    actor=actor,
                    verdict=assessment.verdict,
                    band=assessment.band,
                    redacted_summary=redact(f"{assessment.summary} :: {event.memo}", PII_PATTERNS),
                    citations=assessment.citations,
                    timestamp=utcnow(),
                )
            )
            return assessment

    def _pack_for(self, market: str) -> RulePack:
        try:
            return self._packs[market]
        except KeyError as exc:
            raise ValueError(
                f"no rule pack loaded for market {market!r}; known markets: {sorted(self._packs)}"
            ) from exc

    def _enriched_features(self, event: PaymentEvent, tenant: str) -> FeatureVector:
        """Base features from the port, plus the scam-cue count when a call is linked.

        The voice channel is an enrichment: a payment with no linked call, or a call in a language
        the lexicon does not cover, simply carries a zero scam-cue feature. The verdict never
        depends on a call being present.

        A call that belongs to another tenant is refused by the port and lands in the same place,
        with a zero feature: refusing the enrichment is not refusing the assessment, and the
        response tells the caller nothing about a recording they were not entitled to read.
        """
        base = list(self._features.features_for(event).values)
        hit_count = 0.0
        if event.call_ref and self._conversation_channel is not None:
            try:
                transcript = self._conversation_channel.fetch(event.call_ref, tenant=tenant)
            except (KeyError, ValueError):
                transcript = None
            if transcript is not None:
                hits = scam_lexicon.scan(transcript, self._lexicon)
                hit_count = float(len(hits))
        base = [f for f in base if f.key != scam_lexicon.SCAM_HITS_FEATURE]
        base.append(
            FeatureValue(
                key=scam_lexicon.SCAM_HITS_FEATURE,
                value=hit_count,
                citation=Citation(
                    source_id="scam-lexicon:hit-count",
                    title="Scam-call cues detected",
                    snippet=f"{int(hit_count)} distinct scam-cue entries on the linked call",
                ),
            )
        )
        return FeatureVector(values=tuple(sorted(base, key=lambda f: f.key)))

    def _warning(self, event: PaymentEvent, verdict: object, pack: RulePack) -> tuple[str, str]:
        """Draft a warning through the model seam; validate and fall back deterministically.

        ``verdict`` is an ``EngineVerdict`` (typed loosely to avoid importing the engine's private
        result type into the signature). The fallback is always available and always grounded, so
        an interdiction never blocks on generation and a model can never inject a figure.
        """
        from .interdiction_engine import EngineVerdict

        assert isinstance(verdict, EngineVerdict)
        reason_titles = tuple(reason.title for reason in verdict.reason_codes)
        allowed = {str(verdict.score), str(event.amount_minor // 100)}
        allowed |= figures_in(pack.instrument)
        for reason in verdict.reason_codes:
            allowed |= figures_in(reason.title)
        request = WarningRequest(
            verdict=verdict.verdict,
            market=event.market,
            instrument=pack.instrument,
            reason_titles=reason_titles,
            allowed_figures=tuple(sorted(allowed)),
            locale=_LOCALES.get(event.market, "en"),
        )
        try:
            draft = self._warning_generator.draft(request)
        except Exception:
            draft = ""
        if draft and validate_warning(draft, request):
            return draft.strip(), _WARNING_SOURCE_MODEL
        return build_fallback_warning(request), _WARNING_SOURCE_FALLBACK


#: The customer-facing locale per market, so a warning is drafted in the right language. Data, not
#: an engine branch: a new market adds a row here and a pack file, and no code changes.
_LOCALES: dict[str, str] = {"SG": "en", "AU": "en"}
