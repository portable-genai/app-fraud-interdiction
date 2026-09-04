# Compliance FAQ

For compliance, model-risk and privacy teams assessing this repo's regulatory posture.
Cross-references: [`../../COMPLIANCE.md`](../../COMPLIANCE.md) (the full P-01 to P-13 and R1 to R8
map with an evidence column, plus the adopter-owned crosswalk), [`../../SPEC.md`](../../SPEC.md),
[`../model-card.md`](../model-card.md), [`../practices-audit.md`](../practices-audit.md).

### Is this system stopping customers' payments autonomously?

The deterministic engine ORDERS a verdict; a human disposes of the consequential ones. A `HOLD`
or a `BLOCK` (`domain/kernel.CONSEQUENTIAL_VERDICTS`) sets `requires_human_review` AND is routed
to the `human-review-console` through the shared `review-kit` in the
same call that produced it (dependency rule R8), on the API, the CLI and the agent surface alike.
A `BLOCK` requires two approvals (`_DUAL_CONTROL` in `adapters/_review_payload.py`), because
stopping a customer's money is a two-person decision. The escalation is not a per-repo boolean:
`tests/unit/test_review_routing.py` asserts the ROUTING, not the flag, and the managed router
refuses to run with no console configured rather than swallowing an escalation. What your payment
rail does with a hold is your integration decision, outside this service.

### Who owns the thresholds, and can a model move one?

Your policy function owns them, and no, a model cannot move one. Every number a payment is judged
against lives in `rulepacks/*.yaml` as reviewable data: the baseline, the per-rule threshold and
uplift, the verdict cutoffs and the band cutoffs, each rule carrying the instrument and clause
locator it cites. `domain/interdiction_engine.py` holds no threshold literal and no market
branch. The only model seam is the customer warning text, and even that is validated against the
engine's own output and discarded for a deterministic fallback on any failure. The shipped packs
cite FICTIONAL instruments (`MAS-PSN08-FICTIONAL`, `AU-SPF-DUTY-FICTIONAL`) with invented
locators: they are a worked shape, not policy advice, and `COMPLIANCE.md` says explicitly that
second-line review of the deterministic policy in `domain/` and `rulepacks/` is the adopter's
job, not a vendor default to inherit unexamined.

### How is customer personal data handled?

Unlike an aggregate-data service, this one does see potentially personal text: the free-text
payment memo and, when a call is linked, an already-diarized transcript. So redaction is
unconditional and happens at every boundary before anything leaves the process: before the WORM
audit write, before the `human-review-console` payload (scrubbed against every jurisdiction's rows, not just the
deployment's own, because the console is a shared sink, and including the event id before it
becomes the subject or the idempotency key), and before a tool result can become model context.
The pattern rows and their ORDER are this vertical's choice (`JURISDICTIONS` in `domain/pii.py`,
national-ID rows first and universal email and phone rows last); set them for the markets you
serve. Parties on a `PaymentEvent` are opaque references tokenised upstream, and money is carried
in integer minor units so a verdict is byte-identical on replay. The runtime guardrail and DLP
engine itself is the sibling `agent-guardrail-gateway`, which this repo does NOT bind yet: rule R1 is
marked Partial for exactly that reason, which is survivable today only because no live model call
exists.

### How is the work auditable and reproducible?

Every assessment writes an already-redacted, append-only WORM `AuditEvent` carrying the action,
the verified actor, the verdict, the band, the redacted summary and the citation set. Every
figure in the result is cited: one `ReasonCode` per fired rule, each naming the instrument clause
and the arithmetic (`feature op threshold -> +uplift`), so an auditor can re-derive the score as
baseline plus the sum of the uplifts. The decision is replayable: the engine has no clock (it
reasons over the payment's own `as_of`) and no I/O, and `signal_key` is a SHA-256 fingerprint over
the event, score, verdict and fired rule codes, so two runs diff exactly. The audit trail is
hash-chained AND externally anchored, because a truncated tail leaves a shorter chain that still
verifies; once store and anchor disagree the service refuses to append rather than re-anchoring.
The enterprise WORM sink is `agent-observability`; the in-repo chain is the offline stand-in, and
[security-faq.md](security-faq.md) states its exact limits.

### Is data residency enforced, or only documented?

Enforced at deploy time, and this row was upgraded from Partial to Covered when the enforcement
shipped. `infra/terraform/variables.tf` validates the effective region against the effective
residency allowlist at `terraform plan`, the allowlist defaulting to exactly the region this repo
was rendered for (`render.tf.json`, `asia-southeast1`). `org_policy.tf` pins
`constraints/gcp.resourceLocations` to that region's location group and forbids exportable
service-account keys; the CMEK key ring, the locked WORM audit bucket and, when the opt-in
serving edge is enabled, the Cloud Run service and its regional network endpoint group are all
created in it. `infra/terraform/production_edge.tftest.hcl` is the executable check against a
mocked provider, needing no project and no credentials. The one thing still owed is build wiring:
this repo has no `tf-check` make target and no `terraform` CI job, so those runs happen only when
somebody types `terraform -chdir=infra/terraform test`. `COMPLIANCE.md` P-03 records that TODO
rather than hiding it.

### What is the model-risk story?

Start from the honest baseline: **there is no live model in this repo today.** The managed warning
generator lazily imports the SDK and raises, it is listed in
`managed_readiness.INCOMPLETE_MANAGED_OPERATIONS`, and a `gcp` process refuses to start while it
is bound. What runs is a deterministic template generator. [`../model-card.md`](../model-card.md)
records that boundary, what validates a draft, what happens to a bad one, and the controls still
owed (a pinned model id and version, a token budget, a rate limit and a kill switch, a
managed-profile eval run, and `agent-guardrail-gateway` injection screening). The offline gate
(`eval/run_eval.py --mode smoke`) scores six metrics against the dataset's OWN `expected_*`
oracle, never against the pipeline's own answer: `verdict_accuracy` plus a per-market split for
SG and AU (0.80), `pii_safety` (0.99), `warning_groundedness` (0.99) and `review_safety` (1.0).
Each metric is proven able to go RED before the report is trusted
(`assert_each_can_go_red`), so a metric that cannot fail is caught as a defect. Promotion
authority is not this repo's: `--mode gate` delegates to the sibling `model-quality-gate` AI-quality and
model-risk gate under the bundle id `app-fraud-interdiction` and refuses to run off the managed
profile. Registering that bundle and its thresholds with `model-quality-gate` is an open adopter step (P-08, R5).

### Which regulators does this map to?

`COMPLIANCE.md` maps the catalog's own principles (P-01 to P-13) and dependency rules (R1 to R8)
to concrete controls with an evidence column naming real files, aligned in intent to MAS TRM,
APRA CPS 234 and CPS 230, HKMA and PDPA-class regimes. The mapping from those rows to a specific
regulation, and the judgement that a control is SUFFICIENT for it, is explicitly **adopter-owned**:
it depends on your risk appetite, your regulator, your licence conditions and your existing
control library. No row in that document should be quoted as regulatory assurance. What an
adopter adds in their own control library: the crosswalk to their control ids, the risk
acceptance for every row still Partial or TODO at go-live, the second-line review of the
deterministic policy, and the retention schedule and legal basis for the audit trail this service
writes.

### Are the rows honest about what is missing?

That is the point of the status column. `COMPLIANCE.md` uses Covered, Partial, TODO (repo owner)
and n/a, and a rendered repo starts on TODO for several rows by design, because claiming a
control before it exists is worse than owing it. Currently open and worth knowing before you cite
this document: P-05 grounding and rule R3 (no retrieval port exists, so there is nothing to
ground), P-10 resilience (only the review outbox degrades correctly today), P-11 cost and latency
(no model call to route or cache), R1 (no `GuardrailPort` bound to `agent-guardrail-gateway`), R2 (traces and audit are
not yet in the shared `agent-observability` sink), R4 (the A2A card is served but not registered with `agent-registry`), and
R5 (the `model-quality-gate` bundle is not registered). `../practices-audit.md` records the per-check verdict
against the catalog's common base practices alongside it.

### Can we run it against real payment traffic today?

Not without your own legal, security and model-risk sign-off. Every fixture, every rule pack
number, every instrument name and every lexicon phrase in this repo is obviously fictional, and
the docs say so throughout. The adoption checklist ([`../ADOPTING.md`](../ADOPTING.md) section 6)
lists what must precede any live use: your rule packs and lexicon signed off by a policy owner,
your PII jurisdictions set, your fixtures replaced, your golden set rebuilt, your IdP wired, your
residency region set in both Terraform and the application, your `human-review-console` endpoint configured, and
the managed placeholders implemented and integration-tested.
