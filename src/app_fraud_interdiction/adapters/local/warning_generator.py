"""Local WarningGeneratorPort: a deterministic, grounded stand-in for the model (no SDK).

The offline generator restates the engine's verdict and cited reasons in customer language,
without inventing a figure, so it passes the orchestrator's validation and the demo shows a
"model" warning with no cloud call. It is deliberately NOT the fallback: the fallback
(``domain/warning.build_fallback_warning``) is what ships when a draft is discarded, and keeping
the two distinct is how the fallback path can be tested by making a generator fail.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.kernel import Verdict
from ...domain.warning import WarningRequest

_LEADS: dict[Verdict, str] = {
    Verdict.ALLOW: "This payment was allowed after our scam checks.",
    Verdict.WARN: "Please read this warning before you continue.",
    Verdict.HOLD: "We have placed this payment on hold while we check it for scam signs.",
    Verdict.BLOCK: "This payment was blocked to protect you from a likely scam.",
}


class LocalWarningGenerator:
    """Produce a grounded customer warning deterministically, with no model call."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft(self, request: WarningRequest) -> str:
        lead = _LEADS[request.verdict]
        if request.reason_titles:
            body = " Our checks noted: " + "; ".join(request.reason_titles) + "."
        else:
            body = " No scam indicators were triggered."
        tail = f" If anything feels wrong, contact your bank. Reference: {request.instrument}."
        return lead + body + tail
