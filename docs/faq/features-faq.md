# Features FAQ

For product, financial crime and delivery teams: what this agent does, what is deterministic vs
model, and, importantly, where its responsibilities **stop** and a sibling catalog system takes
over. Cross-references: [`README.md`](../../README.md), [`DEMO.md`](../../DEMO.md),
[`ARCHITECTURE.md`](../../ARCHITECTURE.md).

### What does G3 actually produce?

A cited **interdiction assessment** on one in-flight payment. From a `PaymentEvent` (event id,
event time, market, opaque payer and payee references, amount in minor units, currency, channel,
memo, an optional linked call reference) it produces an `InterdictionAssessment`
(`domain/models.py`) carrying: an allow / warn / hold / block **verdict**, an integer **score**, a
**risk band**, one **`ReasonCode` per rule that fired** with the points it added and the
regulator instrument clause it cites, a **customer-facing warning** with its source recorded, the
`requires_human_review` flag, and `signal_key`, a SHA-256 fingerprint of what drove the decision
so two replays diff exactly. The assessment is written to a redacted WORM audit record in the
same call, and a hold or block is routed to human review before the response returns.

### What is deterministic vs done by a model?

Everything consequential is deterministic, and there is no live model in the repo at all today.
`domain/interdiction_engine.assess` is pure standard library: it walks the market `RulePack`,
fires each rule whose feature crosses its threshold, sums the uplifts onto the baseline, clamps
to 0..100, and maps the score to a verdict and a band using the pack's own cutoffs. It has no
clock (it reasons over `event.as_of`) and no I/O, so the same event always produces the same
answer. The single model seam is `WarningGeneratorPort`, which drafts the customer warning
text, and even that draft is validated against the engine's own output and discarded for a
deterministic fallback on any failure. The managed generator is still a construction-only
placeholder that raises. See [`../model-card.md`](../model-card.md) for the full boundary.

### Where do the thresholds live? Can a bank set its own?

In `rulepacks/*.yaml`, and yes, that is the point. The engine contains no threshold literal and
no market branch. A pack carries the `market`, the citing `instrument`, a `version`, a
`baseline_score`, the verdict cutoffs (`warn`, `hold`, `block`), the band cutoffs (`medium`,
`high`, `critical`) and one row per rule (`code`, `title`, `feature`, `op`, `threshold`,
`uplift`, `locator`). The two shipped packs, `sg_app.yaml` and `au_scam_duty.yaml`, deliberately
carry different numbers so the per-market eval metrics have something to distinguish. Both cite
FICTIONAL instruments. Adding a market is a new pack file plus a row in `MARKET_FILES` and a
locale row, never an engine change.

### What does the linked call add?

An enrichment, never a verdict. When a `PaymentEvent` carries a `call_ref`, the orchestrator
fetches an already-diarized transcript through `ConversationChannelPort` and runs
`domain/scam_lexicon.scan` over the CUSTOMER's turns only, because a victim is coached to repeat
the scammer's lines. The count of distinct lexicon entries that matched becomes the single
numeric feature `scam_call_lexicon_hits`, which the rule packs threshold like any other feature.
The phrases themselves are adopter-owned policy data in `rulepacks/scam_lexicon.yaml`. A payment
with no linked call, or a call in a language the pack does not cover, simply carries a zero on
that feature: a verdict never depends on a call being present. There is no speech recognition in
this repo; the transcript arrives already produced.

### Is anything auto-executed? Does it stop money by itself?

The engine ORDERS a verdict; a human disposes of the consequential ones. Every `HOLD` and every
`BLOCK` sets `requires_human_review` AND is routed to the `human-review-console` Human-Review and Maker-Checker
Console through the shared `review-kit` in the same call that produced it (dependency rule
R8), on the API, the CLI and the agent tool alike. A `BLOCK` demands two approvals. The payload
is redacted before the wire, and the managed router REFUSES when no console is configured rather
than swallowing the escalation. Whether your payment rail acts on a hold is your integration
decision, downstream of this service.

### Which capabilities does this repo own vs integrate from the catalog?

It **owns** the deterministic interdiction decision, the rule packs, the scam lexicon scan, the
grounded warning and the audited, cited result. It **integrates** the cross-cutting concerns
below. Do not rebuild these in a fork.

| Concern | Owned by (catalog id / repo) | G3's role |
|---|---|---|
| Runtime guardrail: prompt-injection defence, output screening | `agent-guardrail-gateway` | NOT integrated yet (no `GuardrailPort`); honestly open as rule R1. Required before untrusted text reaches a live model |
| Governed RAG / ACL-aware knowledge base with citations | `enterprise-knowledge-base` | not used: this vertical retrieves nothing, so rule R3 reads `n/a today` and P-05 stays open |
| Agent registry, versioning, identity, entitlements | `agent-registry` | serves an A2A card at `/.well-known/agent-card.json`; registering it is the adopter's step (R4) |
| AI-quality / eval / model-risk promotion gate | `model-quality-gate` | `eval/run_eval.py --mode gate` delegates the verdict under bundle id `app-fraud-interdiction`; the offline smoke gate mirrors the thresholds (R5) |
| Observability + immutable WORM audit + FinOps | `agent-observability` | `adapters/gcp/tracer.py` sends OTLP there when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; the shared audit sink is rule R2 |
| Human review / maker-checker console | `human-review-console` | routes every hold and block to it in the producing call (R8) |
| Architecture and requirements validation at intake | `architecture-validator` | an intake action; record the validation reference in `COMPLIANCE.md` (R6) |

So the guardrail, the knowledge base, the registry, the eval authority, the shared audit sink and
the review console are *dependencies*, not features of this repo. G3's mandatory dependencies in
the catalog are `agent-guardrail-gateway`, `agent-observability` and `model-quality-gate`.

### How does this relate to the other financial crime systems in the catalog?

G3 is the real-time, in-flight step: score this payment now, warn this customer now, hold or
block before the money leaves. Adjacent FCC systems handle different points and should not be
duplicated here: **G1** AML alert triage and SAR narrative (the post-event alert and the
regulatory filing), **G2** sanctions, PEP and payment-message screening (a different list-matching
decision on the same message), **G4** account-takeover investigation (the session and credential
story, where the payer may not be the customer), and **G5** the SOC fraud-fusion copilot (the
cross-signal operations view). G3's responsibility ends at a routed verdict with a cited warning;
the investigation that follows a confirmed scam belongs to those systems.

### Can I use this for a different jurisdiction, or a different decision?

Yes, and the seams are named. A new market is a rule pack plus a locale row. A different
deterministic decision in the same shape (a screening call, an alert score, an eligibility
verdict) reuses `domain/kernel.py`, the nine ports, the three profiles, the redact-before-audit
rule, the grounded-or-fallback narration pattern, the eval falsification harness and the `human-review-console`
routing, and rewrites `domain/models.py` and the packs. See
[`../ADOPTING.md`](../ADOPTING.md) and [adoption-faq.md](adoption-faq.md).

### How do I see it working?

`make demo` runs the presenter-paced walkthrough: eight narrated steps driving the REAL services
offline, each one asserting that the service actually reached the state the narration claimed.
`make demo-selftest` is the same arc headless and unattended, `make demo-static` renders the
audit-first panels to dependency-free HTML for screenshots, and the CLI does one payment end to
end:

```bash
app_fraud_interdiction interdict sg-block-01 SG payer-coached sg-mule-2d 600000 --call-ref call-scam-sg
```

Everything runs on synthetic, obviously fictional data with no cloud, no network and no API key.
