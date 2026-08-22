"""Minimal stdlib CLI: assess one payment or replay the scripted stream (argparse, no deps).

Prints the score ARITHMETIC (baseline plus one line per fired rule) so the deterministic verdict
is legible on the terminal, and routes every consequential verdict to human review (rule R8).
"""

from __future__ import annotations

import argparse
import sys

from hex_service_kit.logging import configure_logging

from ..config import Container, build_container
from ..domain.kernel import utcnow
from ..domain.models import InterdictionAssessment, PaymentEvent
from ..ports.payment_stream import StreamRequest
from ..service_factory import build_service


def _print_assessment(result: InterdictionAssessment) -> None:
    print(
        f"{result.event_id} [{result.market}]: {result.verdict.value.upper()} "
        f"(score {result.score}, band {result.band.value})"
    )
    for reason in result.reason_codes:
        print(f"  + {reason.uplift:>3}  {reason.code}  {reason.title}")
    print(f"  warning ({result.warning_source}): {result.warning}")
    print(f"  requires_human_review: {result.requires_human_review}")


def _tenant(args: argparse.Namespace, container: Container) -> str:
    """The data scope for this invocation: the flag when given, else the configured tenant.

    The CLI runs with the DEPLOYMENT's identity, so the calls it may read are the deployment's
    own. It is the same flag that already named the Hrz7 partition, because the tenant a call
    belongs to and the tenant a review is filed under are one vocabulary, not two.
    """
    return str(getattr(args, "tenant", "") or container.settings.tenant)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app_fraud_interdiction")
    sub = parser.add_subparsers(dest="command", required=True)

    one = sub.add_parser("interdict", help="Assess a single in-flight payment.")
    one.add_argument("event_id")
    one.add_argument("market", help="Market code, e.g. SG or AU.")
    one.add_argument("payer_ref")
    one.add_argument("payee_ref")
    one.add_argument("amount_minor", type=int, help="Amount in minor units (cents).")
    one.add_argument("--currency", default="SGD")
    one.add_argument("--memo", default="")
    one.add_argument("--call-ref", default="", help="Linked scam-call reference, if any.")
    one.add_argument("--actor", default="cli-user@bank.example")
    one.add_argument("--tenant", default="", help="Tenant partition asserted to Hrz7.")

    stream = sub.add_parser("stream", help="Replay the scripted in-flight payment stream.")
    stream.add_argument("--market", default="", help="Filter to one market code.")
    stream.add_argument("--actor", default="cli-user@bank.example")
    stream.add_argument("--tenant", default="")

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI configures once.
    configure_logging(container.settings.profile, service="app-fraud-interdiction")
    service = build_service(container)

    if args.command == "interdict":
        event = PaymentEvent(
            event_id=args.event_id,
            as_of=utcnow(),
            market=args.market,
            payer_ref=args.payer_ref,
            payee_ref=args.payee_ref,
            amount_minor=args.amount_minor,
            currency=args.currency,
            memo=args.memo,
            call_ref=args.call_ref,
        )
        result = service.assess(event, actor=args.actor, tenant=_tenant(args, container))
        _print_assessment(result)
        if result.requires_human_review:
            ref = container.review_router.route(result, maker=args.actor, tenant=args.tenant)
            print(f"  routed to human review: {ref}")
        return 0

    if args.command == "stream":
        events = container.payment_stream.poll(StreamRequest(market=args.market))
        for event in events:
            result = service.assess(event, actor=args.actor, tenant=_tenant(args, container))
            _print_assessment(result)
            if result.requires_human_review:
                ref = container.review_router.route(result, maker=args.actor, tenant=args.tenant)
                print(f"  routed to human review: {ref}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
