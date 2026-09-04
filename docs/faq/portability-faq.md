# Portability FAQ

For architecture, cloud and exit-planning reviewers who want to know how real the "no lock-in"
claim is and how an off-cloud or sovereign exit would work. Cross-references:
[`../../ARCHITECTURE.md`](../../ARCHITECTURE.md), [`../onprem-migration.md`](../onprem-migration.md),
[`../runbook.md`](../runbook.md).

## What is the no-lock-in claim, concretely?

`src/app_fraud_interdiction/domain/` is pure standard library: no cloud SDK, no web framework, no
HTTP client, and not even a YAML parser (the rule packs arrive already parsed, which is why
`rulepacks_loader.py` lives outside `domain/`). Every outside dependency sits behind a
`@runtime_checkable` `Protocol` in `ports/`, and the whole stack is selected by one setting.
`tests/unit/test_core_purity.py` enforces it rather than trusting it: it walks the core's imports
and fails the build on anything the core does not own, with a control case
(`test_the_scan_can_see_a_violation`) proving the scan can go red and a rule that a written
exemption silences only its own import.

## What are the three profiles?

`SCAMINTERDICT_PROFILE` selects the whole adapter family for all nine ports (`audit`, `identity`,
`review_router`, `tracer`, `evaluation`, `payment_stream`, `features`, `conversation_channel`,
`warning_generator`):

- **`local`**: a real, working, SDK-free offline stack. Seeded dev personas, a hash-chained
  SQLite WORM audit log, a deterministic feature store, a scripted payment stream, scripted call
  transcripts and a template warning generator, all reading one coherent synthetic world
  (`adapters/local/_fixture_data.py`). This is the dev, test and CI default and the working proof
  that the domain runs entirely off-cloud.
- **`gcp`**: the managed services, with every SDK import LAZY (inside the method) so the other
  two profiles import the same module tree with no cloud SDK installed. Be honest about its
  state: four operations are still construction-only placeholders, and
  `managed_readiness.assert_managed_profile_ready` REFUSES to let a managed process start while
  any of them is bound.
- **`onprem`**: fail-fast placeholders that satisfy the same Protocols and RAISE. They are the
  reversibility proof (P-12), not decoration: a review router that silently returned would
  convert every consequential result into an unreviewed one, which is worse than a missing
  feature.

The profile is an exact lookup with no inheritance. A missing `local` or `onprem` binding never
falls back to `gcp`, so a typo cannot silently import a managed SDK or change data custody. An
unknown or emptied value raises at import.

## Is the portability claim tested, or just asserted?

Tested, and bounded. `make portability` (`scripts/portability_demo.py`) runs eight named checks
offline with a pass or fail each and exits non-zero on any failure: every port bound in every
profile, every adapter constructing from a single `Settings` and conforming to its Protocol, the
offline family ANSWERING, the exit family REFUSING, an in-place record rewrite detected, an
anchored trail detecting truncation with its control case, the trail exporting and reloading
outside this codebase, and no cloud SDK imported along the way. It also prints what it does NOT
prove, rather than overclaiming. Alongside it, `tests/contract/test_port_parity.py` asserts set
equality across the FIVE places a port must be registered (`ports/__init__.py` `PORT_PROTOCOLS`,
`config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`, and a `PortCase` in
`tests/contract/canonical.py`), in both directions, and
`tests/contract/test_behavioral_parity.py` proves the same canonical request behaves the same at
each family's boundary.

## How would a sovereign or on-prem exit actually go?

The `onprem` family is the scaffold: each fail-fast placeholder marks a seam where a client
supplies their own component (their payment stream, their feature store, their voice channel,
their model host, their IdP, their audit store, their review console). Because the domain never
changes, the exit is an adapter exercise rather than a rewrite, and the rule packs and the scam
lexicon are already plain YAML files you own. See [`../onprem-migration.md`](../onprem-migration.md)
for the migration guide.

## How is data residency handled, and is it enforced or just described?

Enforced at deploy time. The region is chosen once: `infra/terraform/render.tf.json` carries the
rendered region (`asia-southeast1`), and `infra/terraform/variables.tf` validates the EFFECTIVE
region against the EFFECTIVE residency allowlist at `terraform plan`, with the allowlist
defaulting to exactly the rendered region. `org_policy.tf` pins
`constraints/gcp.resourceLocations` to that region's location group and forbids exportable
service-account keys; the CMEK key ring (`kms.tf`), the locked WORM audit bucket
(`logging_worm.tf`) and, when the opt-in serving edge is enabled, the Cloud Run service and its
regional network endpoint group (`production_edge.tf`) are all created in it.
`infra/terraform/production_edge.tftest.hcl` is the executable check, running against a mocked
provider with no project and no credentials. The application half agrees: `GCP_REGION` feeds
`Settings.region`, which `/healthz` and the agent card report, so a drifting deployment is
visible as well as prevented. The one honest gap is build wiring, and
[`../../COMPLIANCE.md`](../../COMPLIANCE.md) P-03 says so: there is no `tf-check` make target and
no `terraform` CI job, so `terraform -chdir=infra/terraform test` runs only when somebody types
it. A fork should wire it in.

## Can the data be exported in an open format?

Yes. The audit trail exports to and restores from JSON Lines through the commons' hash-chained
log, and `portability_demo.py` proves a reload OUTSIDE this codebase rather than a round trip
inside it. The rule packs, the scam lexicon and the eval golden set are already plain YAML and
JSONL in the repository, so the policy that produced any decision is portable by inspection. The
decision itself is replayable: `signal_key` is a content fingerprint over the event, the score,
the verdict and the fired rule codes, so an auditor can re-run the same event through the same
pack and diff exactly.

## What is honestly NOT portable, or not yet real?

Three things, stated rather than hidden. First, tamper-evidence and export-reload are scoped to
what the local sink can prove; production tamper-evidence is the locked Cloud Logging bucket and
`agent-observability`, reached through the managed audit adapter. Second, four managed adapters are
construction-only today (`CcaiConversationChannel.fetch`, `VertexFeatureStore.features_for`,
`BigQueryPaymentStream.poll`, `VertexWarningGenerator.draft`), so the `gcp` profile is a proven
binding surface rather than a proven integration, and the preflight refuses to pretend otherwise.
Third, the `onprem` family raises by design: it proves the seams exist, it does not implement
them for you.
