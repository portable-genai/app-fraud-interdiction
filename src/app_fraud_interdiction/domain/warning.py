"""The customer warning: what a model may draft, and the deterministic floor under it.

An interdiction verdict must never wait on generation, and it must never let a model invent a
figure. So the warning has two layers:

* :func:`build_fallback_warning` is a pure, deterministic, pack-cited template. It is always
  available, needs no model, and is what ships when generation is slow, unreachable, or produces
  something that fails validation.
* :func:`validate_warning` is the gate a MODEL draft must pass to be used instead of the
  fallback: it is length-capped, it must name the action the engine ordered, and every figure it
  contains must appear in the engine's own output (:data:`WarningRequest.allowed_figures`). A
  draft that invents a number, or that is empty, or that runs long, is discarded.

The model's job is narrow: restate the deterministic verdict and its cited reasons in
locale-aware customer language. It owns no number and no verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .kernel import Verdict

#: The longest a customer-facing warning may be. A model draft over this is discarded: an
#: interdiction warning is a short, scannable message, not an essay.
MAX_WARNING_CHARS = 480

#: Every maximal run of digits in a candidate warning, so grounding can check each against the
#: figures the engine actually produced.
_DIGIT_RUN = re.compile(r"\d[\d,]*")

#: The customer-facing verb each verdict must be describable by. A warning that does not name the
#: action the engine ordered is not describing this decision.
_ACTION_WORD: dict[Verdict, str] = {
    Verdict.ALLOW: "allowed",
    Verdict.WARN: "warning",
    Verdict.HOLD: "hold",
    Verdict.BLOCK: "blocked",
}


@dataclass(frozen=True, slots=True)
class WarningRequest:
    """Everything a warning may be built from: the verdict, the cited reasons, the safe figures."""

    verdict: Verdict
    market: str
    instrument: str
    reason_titles: tuple[str, ...]
    allowed_figures: tuple[str, ...]
    locale: str = "en"


def figures_in(text: str) -> set[str]:
    """The digit runs in ``text``, normalised by stripping thousands separators.

    Used both to grade a draft (what figures does it contain?) and to build the allowed set from
    the engine's own deterministic output (what figures may a draft legitimately contain?).
    """
    return {match.group(0).replace(",", "") for match in _DIGIT_RUN.finditer(text)}


def _figures(text: str) -> set[str]:
    return figures_in(text)


def validate_warning(text: str, request: WarningRequest) -> bool:
    """True when a model draft may be used: bounded, on-topic, and inventing no figure.

    The grounding check is the load-bearing one: a warning that mentions an amount or a score the
    engine never produced is worse than no warning, so every digit run in the draft must be one of
    ``request.allowed_figures``. This is what the eval's groundedness metric asserts too.
    """
    stripped = text.strip()
    if not stripped or len(stripped) > MAX_WARNING_CHARS:
        return False
    if _ACTION_WORD[request.verdict] not in stripped.lower():
        return False
    allowed = {figure.replace(",", "") for figure in request.allowed_figures}
    return _figures(stripped) <= allowed


def build_fallback_warning(request: WarningRequest) -> str:
    """A deterministic, pack-cited warning that is always available and always grounded.

    Names the action the engine ordered and the reasons it cited, in plain language, with no
    figure the engine did not produce. This is the floor: an interdiction warning always exists,
    whether or not a model was reachable.
    """
    action = _ACTION_WORD[request.verdict]
    if request.verdict is Verdict.ALLOW:
        lead = "This payment was allowed."
    elif request.verdict is Verdict.WARN:
        lead = "Please pause: this payment shows signs of a scam."
    elif request.verdict is Verdict.HOLD:
        lead = "This payment is on hold while our team reviews it for signs of a scam."
    else:
        lead = "This payment was blocked because it strongly matches a known scam pattern."
    if request.reason_titles:
        reasons = "; ".join(request.reason_titles)
        body = f" Why: {reasons}."
    else:
        body = ""
    tail = f" Reference: {request.instrument}. Status: {action}."
    return (lead + body + tail).strip()
