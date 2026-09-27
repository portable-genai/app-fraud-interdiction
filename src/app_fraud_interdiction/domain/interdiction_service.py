"""The interdiction orchestrator: deterministic verdict, grounded warning, redact-before-audit.

This is the pure-stdlib heart of the vertical. It pulls cited features for a payment, runs the
deterministic engine (whose verdict a model can never move), optionally folds in scam-cue hits from
a linked call, drafts a customer warning through the one model seam, VALIDATES that draft against
the engine's own output and discards it for a deterministic fallback on any failure, then redacts
and writes a WORM audit record. It routes nothing itself: rule R8 routing to the
human-review-console is the surfaces' job, so the same escalation is routed once, on whichever
surface produced it (``api/app.py``, ``cli/main.py``, ``agent/tools.py``).

Rule R1: the guardrail screens BOTH directions of the one generation call this service makes,
the customer-warning draft through ``WarningGeneratorPort`` (whatever the bound adapter is, a live
model inherits this screening unchanged, because it wraps the STEP, not the adapter). INPUT: the
prompt the generator is handed, every field of the :class:`~.warning.WarningRequest` serialised
as sent (the market is the caller's, the rest is the engine's and the pack's), before a draft is
requested. OUTPUT: the draft, before it is validated, audited or returned; the screened text is
used exactly as given. A block, and a guardrail that raised instead of deciding, are audited as a
separate ``guardrail_blocked`` record the moment they happen, and the warning then falls back to
the deterministic, pack-cited template: narration is optional here BY DESIGN (an interdiction
never waits on generation), so a refusal never returns a partial or unscreened draft and never
stops the verdict, which a model cannot move anyway. ``warning_source`` says
``guardrail_blocked`` on that assessment.

Everything here is injected as a port Protocol or a pure value, so nothing in this module imports
a web framework, a cloud SDK or a YAML parser: the packs and the lexicon are handed in already
parsed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from pii_kit import redact
from speech_lexicon_kit import Lexicon

from ..ports.audit import AuditSinkPort
from ..ports.conversation_channel import ConversationChannelPort
from ..ports.features import FeaturePort
from ..ports.guardrail import GuardrailPort
from ..ports.observability import ObservabilityTracerPort
from ..ports.warning_generator import WarningGeneratorPort
from . import scam_lexicon
from .interdiction_engine import EngineVerdict
from .interdiction_engine import assess as engine_assess
from .kernel import AuditEvent, Citation, Direction, GuardrailVerdict, utcnow
from .models import FeatureValue, FeatureVector, InterdictionAssessment, PaymentEvent
from .pii import PII_PATTERNS
from .rulepack import RulePack
from .warning import WarningRequest, build_fallback_warning, figures_in, validate_warning

_WARNING_SOURCE_MODEL = "model"
_WARNING_SOURCE_FALLBACK = "fallback"
#: The guardrail refused one direction of the draft, or could not decide (rule R1); the
#: deterministic fallback ships, exactly as it does for a raising or a lying generator.
_WARNING_SOURCE_BLOCKED = "guardrail_blocked"

#: The audit action of a guardrail refusal: its own WORM record, written when the refusal happens
#: and before the assessment's own ``interdict`` record, so the trail holds every refused draft
#: and ``infra/terraform/monitoring.tf`` can alert on it by this exact value.
GUARDRAIL_BLOCKED_ACTION = "guardrail_blocked"

_log = logging.getLogger(__name__)

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
        guardrail: GuardrailPort,
        packs: Mapping[str, RulePack],
        lexicon: Lexicon,
        conversation_channel: ConversationChannelPort | None = None,
    ) -> None:
        self._features = features
        self._warning_generator = warning_generator
        self._audit = audit
        self._tracer = tracer
        self._guardrail = guardrail
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

            warning, source = self._warning(event, verdict, pack, actor=actor)
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

    def _warning(
        self, event: PaymentEvent, verdict: EngineVerdict, pack: RulePack, *, actor: str
    ) -> tuple[str, str]:
        """Draft a warning through the model seam; screen, validate and fall back deterministically.

        The fallback is always available and always grounded, so an interdiction never blocks on
        generation and a model can never inject a figure.

        Rule R1: the prompt is screened INPUT before a draft is requested, and the draft OUTPUT
        before it is validated or used. Either direction refused, or a guardrail that could not
        decide, is audited ``guardrail_blocked`` and ships the deterministic fallback.
        """
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
        fallback = build_fallback_warning(request)
        refusal = _Refusal(event=event, verdict=verdict, actor=actor)

        # 1) INPUT, before a draft is requested. The generator takes the request STRUCTURED, so
        # a screen that rewrote the serialised prompt has handed back text no field of it can
        # carry: that is refused too, rather than drafting from the unscreened original.
        prompt = warning_prompt(request)
        screened_prompt = self._screen(prompt, Direction.INPUT, refusal)
        if screened_prompt is None:
            return fallback, _WARNING_SOURCE_BLOCKED
        if screened_prompt != prompt:
            self._audit_blocked(
                refusal, Direction.INPUT, "the guardrail rewrote the structured warning request"
            )
            return fallback, _WARNING_SOURCE_BLOCKED

        try:
            draft = self._warning_generator.draft(request)
        except Exception:
            draft = ""
        if not draft:
            return fallback, _WARNING_SOURCE_FALLBACK

        # 2) OUTPUT, before the draft is validated, audited or returned. The screened text is the
        # draft from here on, exactly as given, never the unscreened original.
        screened_draft = self._screen(draft, Direction.OUTPUT, refusal)
        if screened_draft is None:
            return fallback, _WARNING_SOURCE_BLOCKED
        if screened_draft and validate_warning(screened_draft, request):
            return screened_draft.strip(), _WARNING_SOURCE_MODEL
        return fallback, _WARNING_SOURCE_FALLBACK

    def _screen(self, text: str, direction: Direction, refusal: _Refusal) -> str | None:
        """Screen one text in one direction: the text to use from here on, or ``None`` if refused.

        A block, and a guardrail that raised instead of deciding (its backend errored or timed
        out, or the on-premises placeholder is bound), both fail CLOSED behind an audited
        ``guardrail_blocked`` record. Neither raises out of here: the warning is optional by
        design and the deterministic fallback replaces it, so the verdict is never held up.
        """
        try:
            verdict: GuardrailVerdict = self._guardrail.screen(text, direction)
        except Exception as exc:
            _log.warning(
                "guardrail could not screen the warning %s (%s); the fallback ships",
                direction.value,
                type(exc).__name__,
            )
            self._audit_blocked(refusal, direction, f"guardrail unavailable ({type(exc).__name__})")
            return None
        if not verdict.allowed or verdict.sanitized_text is None:
            reason = verdict.reason or f"warning {direction.value} blocked by guardrail"
            self._audit_blocked(refusal, direction, reason)
            return None
        return verdict.sanitized_text

    def _audit_blocked(self, refusal: _Refusal, direction: Direction, reason: str) -> None:
        """Audit a guardrail refusal as its own record, when it happens (rule R1/R2).

        Never carries the refused text: only that a refusal happened, for which payment, in
        which direction and why, with the engine's verdict and band, which the refusal did not
        change. The payment's own ``interdict`` record follows it as usual.
        """
        self._audit.record(
            AuditEvent(
                action=GUARDRAIL_BLOCKED_ACTION,
                actor=refusal.actor,
                verdict=refusal.verdict.verdict,
                band=refusal.verdict.band,
                redacted_summary=redact(
                    f"{refusal.event.event_id}: warning draft blocked ({direction.value}): "
                    f"{reason}",
                    PII_PATTERNS,
                ),
                citations=(),
                timestamp=utcnow(),
            )
        )


@dataclass(frozen=True, slots=True)
class _Refusal:
    """What a guardrail refusal record may state: the payment, its verdict, who asked."""

    event: PaymentEvent
    verdict: EngineVerdict
    actor: str


#: The customer-facing locale per market, so a warning is drafted in the right language. Data, not
#: an engine branch: a new market adds a row here and a pack file, and no code changes.
_LOCALES: dict[str, str] = {"SG": "en", "AU": "en"}


def warning_prompt(request: WarningRequest) -> str:
    """The prompt the INPUT screen reads: every field the generator is handed, as sent.

    The generator takes the :class:`~.warning.WarningRequest` itself, so this is the text a
    model call built from it would carry: nothing the generator can read is left out of the
    screen. One field per line, so no phrase can run from one field into the next unseen.
    """
    return "\n".join(
        (
            f"verdict: {request.verdict.value}",
            f"market: {request.market}",
            f"locale: {request.locale}",
            f"instrument: {request.instrument}",
            *(f"reason: {title}" for title in request.reason_titles),
            f"figures: {', '.join(request.allowed_figures)}",
        )
    )
