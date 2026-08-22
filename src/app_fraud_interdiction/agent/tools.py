"""Tool functions an agent runtime calls: thin, side-effect-honest wrappers on the services.

Design rules, in the order they matter:

* **No business logic here.** The domain service decides HOW; the model only decides WHICH tool
  to call. A rule that lives in a tool wrapper is a rule the CLI and the API do not have.
* **Rule R8 applies on this path too.** An escalated result is ROUTED from inside the tool, in
  the same call that produced it. An agent surface that only returned the flag would be a third
  place an escalation can quietly stop, after the API and the CLI.
* **Import-safe without a runtime.** ``google.adk`` is imported lazily inside
  :func:`build_function_tools`, so these callables are importable, testable and runnable with
  no ADK and no cloud SDK installed.
* **Typed and documented.** A runtime derives each tool's name, description and JSON parameter
  schema from the signature and the docstring, so both are part of the contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hex_service_kit.serialization import to_jsonable
from pii_kit import redact

from ..config import Container, Settings, build_container
from ..domain.kernel import utcnow
from ..domain.models import PaymentEvent
from ..domain.pii import PII_PATTERNS
from ..ports.payment_stream import StreamRequest
from ..service_factory import build_service

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

#: The identity a tool call is attributed to when the runtime propagates none. It names the
#: SERVICE, not a person, so an unattributed action is never mistaken for a human's.
DEFAULT_ACTOR = "app-fraud-interdiction-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _redacted(node: Any) -> Any:
    """Mask personal data in every string of a tool result, however deeply it is nested.

    A tool result is not an API response. The API returns to the authenticated caller the text
    that caller just submitted; a TOOL result goes into a model's context, and P-04 says
    minimise the data that reaches a model. The evidence snippet a caller may legitimately read
    back is therefore masked here, on the way to the agent, using the same pattern pack the
    audit write masks with. Walking the whole structure rather than three named fields means a
    future field cannot arrive unredacted just because nobody remembered to add it.
    """
    if isinstance(node, str):
        return redact(node, PII_PATTERNS)
    if isinstance(node, dict):
        return {key: _redacted(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_redacted(value) for value in node]
    return node


def assess_payment(
    event_id: str,
    market: str,
    payer_ref: str,
    payee_ref: str,
    amount_minor: int,
    currency: str = "SGD",
    memo: str = "",
    call_ref: str = "",
    actor: str = DEFAULT_ACTOR,
    tenant: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Assess one in-flight payment and route it for human review when it holds or blocks.

    The verdict, score and band are computed by the deterministic engine (a model can never move
    a hold or a block). Writes an already-redacted audit event, and, when the verdict is
    consequential, submits it to the human-review console (rule R8).

    Args:
      event_id: The payment event's own identifier.
      market: Market code (e.g. SG, AU); selects the rule pack.
      payer_ref: Opaque reference to the paying party.
      payee_ref: Opaque reference to the payee.
      amount_minor: Amount in minor units (cents).
      currency: ISO currency code.
      memo: Free-text payment memo (redacted before audit).
      call_ref: Linked scam-call reference, if any.
      actor: The verified identity this call is attributed to.
      tenant: Tenant partition asserted on an outbound review.

    Returns:
      A JSON-safe result dict with every string masked for personal data (P-04: a tool result
      goes into a model's context), plus ``review_ref``: where the escalation WENT. It is empty
      only when the verdict was not consequential, so a caller can tell a routed escalation from a
      flag nobody read.
    """
    container = _container(settings)
    event = PaymentEvent(
        event_id=event_id,
        as_of=utcnow(),
        market=market,
        payer_ref=payer_ref,
        payee_ref=payee_ref,
        amount_minor=amount_minor,
        currency=currency,
        memo=memo,
        call_ref=call_ref,
    )
    scope = tenant or container.settings.tenant
    result = build_service(container).assess(event, actor=actor, tenant=scope)
    review_ref = ""
    if result.requires_human_review:
        review_ref = container.review_router.route(result, maker=actor, tenant=tenant)
    payload = _redacted(to_jsonable(result))
    if not isinstance(payload, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("an interdiction assessment must serialise to a JSON object")
    # Attached after the redaction pass: it is a routing reference, not narrative text, and
    # masking an identifier would break the caller's ability to look the review up.
    payload["review_ref"] = review_ref
    return payload


def list_payment_stream(
    market: str = "",
    max_events: int = 100,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """List the in-flight payments waiting on the stream, without scoring them.

    Args:
      market: Optional market code to filter the stream to.
      max_events: Cap on the number of events returned.

    Returns:
      A JSON-safe dict with a ``events`` list, every string masked for personal data.
    """
    container = _container(settings)
    events = container.payment_stream.poll(StreamRequest(market=market, max_events=max_events))
    payload = _redacted({"events": [to_jsonable(event) for event in events]})
    if not isinstance(payload, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("a payment stream listing must serialise to a JSON object")
    return payload


def verify_audit_trail(settings: Settings | None = None) -> dict[str, Any]:
    """Verify the audit trail's hash chain and its external head anchor.

    Returns:
      A dict with ``ok``, the record counts and a ``detail`` string. ``ok`` is false for an
      edited, deleted or reordered record, and, when an external anchor is configured, for a
      truncated tail as well. Without an anchor a truncation cannot be detected, and the detail
      says so rather than implying a stronger guarantee than the store provides.
    """
    resolved = settings or Settings.load()
    audit = _container(resolved).audit
    verify = getattr(audit, "verify", None)
    if verify is None:
        raise NotImplementedError(
            f"the {resolved.profile} audit adapter does not expose chain verification; a "
            "managed WORM sink is verified by its own retention policy, not from here"
        )
    report = verify()
    return {
        "ok": report.ok,
        "entries": report.entries,
        "chained": report.chained,
        "legacy": report.legacy,
        "first_bad_seq": report.first_bad_seq,
        "detail": report.detail,
        "anchored": bool(resolved.audit_anchor_path),
    }


#: The tool table. The agent card advertises exactly these, by function name.
TOOL_FUNCTIONS = (assess_payment, list_payment_stream, verify_audit_trail)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each callable as a runtime FunctionTool (the only ADK-dependent code path).

    The import is deliberately here rather than at module scope: without it this module, the
    card and every tool would need an agent runtime installed to be imported at all, and the
    offline gate installs none.
    """
    # No ignore comment: the missing-import error for this module is already reported (and
    # ignored) at the TYPE_CHECKING import above, and a second one would be flagged as unused.
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=function) for function in TOOL_FUNCTIONS]
