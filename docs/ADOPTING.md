# Adopting this repo as your base

This repository (G3, Scam and APP Interdiction) is a **common base** that a bank, a payment
institution or another regulated firm forks to build its own **real-time scam and
authorised-push-payment interdiction service**: something that scores an in-flight payment
against a market rule pack, orders an allow / warn / hold / block verdict deterministically,
hands the customer a warning that cannot contain a figure the engine did not produce, and routes
every hold and block to a human reviewer in the same request that produced it. It ships a
reusable hexagonal core (a pure-stdlib domain, nine typed ports, three swappable adapter
families, a green offline gate) plus a fully worked two-market vertical (SG and AU, both with
fictional policy numbers) that you can keep, retune, or replace with your own jurisdictions.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and the request
> pipeline), [`SPEC.md`](../SPEC.md) (the locked contracts), [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> (the file-by-file touch list for a new adapter or port), [`model-card.md`](model-card.md) (the
> model boundary as built), and the [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The core is hexagonal, and the boundary between reusable machinery and this vertical is a
physical module split. `domain/kernel.py` owns the vertical-neutral contracts (`Citation`,
`AuditEvent`, `RiskBand`, `Verdict`, `CONSEQUENTIAL_VERDICTS`, `utcnow`) and knows nothing about
payments; `domain/models.py` holds only the G3 artifacts. A fork building a different financial
crime vertical rewrites `models.py` and leaves `kernel.py` alone.

| Layer | Where | For a new vertical or market |
|---|---|---|
| **Vertical-neutral machinery** | `domain/kernel.py`, every Protocol in `ports/`, the identity vocabulary in `ports/identity.py`, the container wiring in `config.py`, the redacted review conversion in `adapters/_review_payload.py`, the eval harness mechanics in `eval/run_eval.py` | keep untouched |
| **Policy (your numbers)** | the score cutoffs, band cutoffs, per-rule thresholds, uplifts and instrument locators in `rulepacks/sg_app.yaml` and `rulepacks/au_scam_duty.yaml`; the coached phrases in `rulepacks/scam_lexicon.yaml`; `JURISDICTIONS` in `domain/pii.py`; `MAX_WARNING_CHARS` in `domain/warning.py`; `_LOCALES` in `domain/interdiction_service.py`; `THRESHOLDS` in `eval/run_eval.py` | change deliberately (see section 4) |
| **Vertical (the interdiction artifacts)** | the G3 models in `domain/models.py` (`PaymentEvent`, `FeatureValue`, `FeatureVector`, `ScamLexiconHit`, `ReasonCode`, `InterdictionAssessment`), the local fixtures in `adapters/local/_fixture_data.py`, the golden set in `eval/datasets/golden_cases.jsonl`, the UI panels in `ui/`, the demo arc in `scripts/demo.py` | rewrite or reseed for your data |

Note what is NOT in the policy row: `domain/interdiction_engine.py` carries no threshold literal
and no market branch at all. It reads `RulePack.baseline_score`, the per-rule `uplift`, the
`warn_at` / `hold_at` / `block_at` cutoffs and `band_for()`, so adding a market is a new
`rulepacks/<market>.yaml` file plus one row in `MARKET_FILES` (`rulepacks_loader.py`) and one
locale row, never an engine edit. If your product is another deterministic financial crime
decision (screening, alert triage, takeover scoring), the hexagon, the three profiles, the
redact-before-audit rule, the grounded-or-fallback warning pattern, the eval gate and the Hrz7
routing all transfer directly.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): `domain/kernel.py`, `domain/interdiction_engine.py`,
  `domain/rulepack.py`, `domain/warning.py`, `ports/`, `config.py`, `adapters/_review_payload.py`,
  `managed_readiness.py`, `tests/contract/`, the eval harness mechanics (`eval/run_eval.py`), the
  CI workflows and the demo mechanics in `scripts/`.
- **Adopter-owned** (yours; expect to edit): every file in `rulepacks/`, `config/settings.yaml`
  *values*, `domain/pii.py` (`JURISDICTIONS`), the `_LOCALES` map, the local fixtures
  (`adapters/local/_fixture_data.py`, `tests/fixtures/sample_cases.py`), `adapters/onprem/*`,
  `ui/` theming and branding, `eval/datasets/golden_cases.jsonl` and the `THRESHOLDS` block, the
  `infra/terraform/*.tfvars` values, and the jurisdiction rows in
  [`COMPLIANCE.md`](../COMPLIANCE.md).

Track upstream via git tags; rebase your adopter-owned changes onto each release rather than
merging `main` continuously, so conflicts stay in files you were told to expect.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the python package name `app_fraud_interdiction` (which is ALSO
the console-script name: see `[project.scripts]` in `pyproject.toml`), the `SCAMINTERDICT`
environment prefix behind every `SCAMINTERDICT_*` variable, the distribution and resource id
`app-fraud-interdiction`, and optionally the Terraform `name_prefix` default `g3-svc`. Preview
first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_scam_interdiction \
    --env-prefix ACMESCAM --resource acme-scam-interdiction \
    --name-prefix acme-scam --dry-run

# Apply:
python scripts/rename_fork.py --package acme_scam_interdiction \
    --env-prefix ACMESCAM --resource acme-scam-interdiction \
    --name-prefix acme-scam --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
```

Three things about the flags are worth knowing before you run it:

- There is deliberately **no `--cli` flag**. The console script is named after the package, so
  `--package` renames it too; a second flag could only drift out of step with the first.
- There is deliberately **no `--dist` flag**. `--resource` is one literal doing four jobs: the
  distribution name in `pyproject.toml`, the GitHub id in `[project.urls]`, the A2A agent-card
  name (`agent/agent_card.py`) and the Hrz4 eval bundle id (`_BUNDLE` in `eval/run_eval.py` and
  in `adapters/gcp/evaluation.py`). They are the same string on purpose, so a fork's promotion
  record and its discovery card cannot disagree about which system they describe.
- `--name-prefix` is optional and is rewritten ONLY inside its own variable block in
  `infra/terraform/variables.tf`. Its current value is read from that file rather than hardcoded,
  and the script applies the same `^[a-z][a-z0-9-]{2,18}$` rule Terraform enforces, so a bad
  prefix fails at rename time instead of at somebody's first `terraform plan`.

Add `--include-docs` to sweep Markdown prose too; a default run leaves it alone so the diff stays
reviewable. The script deliberately does NOT touch the human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region and residency.** The region is chosen once and it is ENFORCED at deploy time, not
   merely described. `infra/terraform/render.tf.json` carries the rendered region
   (`asia-southeast1`); `infra/terraform/variables.tf` validates the effective region
   (`coalesce(var.region, local.render_region)`) against the effective residency allowlist
   (`var.allowed_regions`, defaulting to exactly the rendered region) at plan time. To move a
   fork in-country you set BOTH `region` and `allowed_regions` in your tfvars, and point the
   application at the same place with `GCP_REGION` (which `config/settings.yaml` reads into
   `Settings.region`, and which `/healthz` and the agent card then report). Setting one without
   the other fails at `terraform plan` on purpose. What ships already: the
   `constraints/gcp.resourceLocations` Org Policy pinned to that region's location group
   (`org_policy.tf`), the regional CMEK key ring (`kms.tf`), the locked WORM audit bucket
   (`logging_worm.tf`), and the region assertions in `infra/terraform/production_edge.tftest.hcl`.
   The one piece still owed is build wiring: this repo has no `tf-check` make target and no
   `terraform` CI job, so `terraform -chdir=infra/terraform test` only runs when somebody types
   it. Wire it into your pipeline. See [`runbook.md`](runbook.md).
2. **Identity and your IdP.** This repo owns no login flow and never will. The `gcp` profile
   verifies the IAP-injected assertion in `adapters/gcp/identity.py` against the audience you
   configure in `SCAMINTERDICT_IAP_AUDIENCE`; an unset or emptied audience REFUSES every caller,
   because `audience=None` means the audience is not verified and would accept any Google-signed
   token from any project. The `local` profile uses seeded dev personas resolved from
   `X-Dev-Persona`, and it refuses to construct unless `SCAMINTERDICT_PROFILE` was set to `local`
   DELIBERATELY. The `onprem` profile is a placeholder that raises, which is where you implement
   your own IdP adapter. Wire auth ON the deployed service; do not add a login route here.
3. **The rule packs are your policy, and they are the whole policy.** Every number a payment is
   judged against lives in `rulepacks/`, not in code: the `thresholds:` block (`warn`, `hold`,
   `block`), the `bands:` block (`medium`, `high`, `critical`), the `baseline_score`, and per rule
   the `feature`, `op`, `threshold`, `uplift` and `locator`. The shipped packs cite fictional
   instruments (`MAS-PSN08-FICTIONAL`, `AU-SPF-DUTY-FICTIONAL`) with invented clause locators;
   they are a worked shape, not policy advice. Your first line and second line own these numbers.
   The feature vocabulary the rules threshold is `new_payee`, `amount_major`, `payee_age_days`,
   `velocity_24h`, `device_change` and `scam_call_lexicon_hits`; a rule naming a feature your
   store does not produce simply never fires, so keep the pack and the feature adapter in step.
4. **The scam lexicon and the rule packs are adopter-owned policy data.** The top-level
   `rulepacks/` directory is deliberately outside `src/`: it is data a policy owner reviews and
   signs off, not code an engineer edits. That includes `rulepacks/scam_lexicon.yaml`, the
   coached-secrecy and fake-authority phrases a victim is talked into repeating on a call.
   Those phrases live here rather than in the shared `speech-lexicon-kit`, because the kernel
   carries the matcher and the consumer carries the phrases: a wording change is a pack edit in
   your fork, never a release of a package every repo pins. Expect to rewrite all three files,
   in your languages, with your own fraud team's cues, and to keep the `locale:` honest, because
   `domain/scam_lexicon.scan` treats a locale mismatch as "this call is out of scope" and yields
   no hits rather than failing the interdiction.
5. **Redaction scope.** `JURISDICTIONS` in `domain/pii.py` selects which national-ID pattern rows
   the audit write masks with, and the order matters (national rows first, universal email and
   phone rows last). The outbound review payload is scrubbed harder, against EVERY jurisdiction's
   rows (`adapters/_review_payload.py`), because the Hrz7 console is a shared sink. Set your
   jurisdictions before you point this at anything real.
6. **Fixtures and reference data are fictional, all of them.** The local feature store, the
   scripted payment stream and the scripted call transcripts (`adapters/local/_fixture_data.py`),
   the shared test cases (`tests/fixtures/sample_cases.py`) and the golden set
   (`eval/datasets/golden_cases.jsonl`) use obviously invented parties and `.example` domains.
   **Do not run against real payment traffic without your own legal, security and model-risk
   sign-off.**
7. **The eval golden set and its thresholds.** `eval/run_eval.py` scores six metrics against the
   dataset's OWN `expected_*` oracle: `verdict_accuracy` plus a per-market
   `verdict_accuracy_SG` / `verdict_accuracy_AU` split, `pii_safety` (0.99), `warning_groundedness`
   (0.99) and `review_safety` (1.0). A fork inherits a green gate that measures the WRONG rulebook
   until you rebuild the golden cases, and the per-market metrics are keyed by market code, so a
   fork that renames its markets edits `THRESHOLDS` and the `per_market_scores` seed together.
   The falsification harness (`_falsify`) proves each metric can go red before any report is
   trusted; keep it, and extend it when you add a metric.
8. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001,
   `HEALTHCHECK` on `/healthz`), the whole of `infra/terraform/` (Org Policy, CMEK, the locked
   WORM bucket, the dry-run-first VPC-SC perimeter, the opt-in serving edge), and the
   loopback-by-default API binding before you expose anything. Note the fail-closed preflight in
   `managed_readiness.py`: four managed adapters are still construction-only placeholders
   (`CcaiConversationChannel.fetch`, `VertexFeatureStore.features_for`,
   `BigQueryPaymentStream.poll`, `VertexWarningGenerator.draft`), and a `gcp` process REFUSES to
   start while any of them is bound. Implement and integration-test each one, remove its entry
   from `INCOMPLETE_MANAGED_OPERATIONS`, and only then flip Terraform's
   `managed_profile_implemented`.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it *touches* are
owned by sibling platform services; integrate rather than rebuild them (see
[`faq/features-faq.md`](faq/features-faq.md) for the full map). G3's mandatory dependencies are
Hrz1, Hrz5 and Hrz4.

- **Hrz1** guardrail gateway: NOT integrated yet, and honestly marked as such (`COMPLIANCE.md`
  rule R1). Redaction is in place at every boundary, but there is no `GuardrailPort`. Bind one
  before untrusted text (a customer memo, a call transcript) reaches a live model.
- **Hrz2** governed knowledge base: not used. This vertical retrieves nothing, so rule R3 reads
  `n/a today` and P-05 is an open TODO. A fork that adds retrieval takes both on.
- **Hrz3** agent registry: the A2A card is built and served at `/.well-known/agent-card.json`
  from the same tool table the runtime binds (`agent/agent_card.py`). Registering it and taking
  the agent's identity and entitlements from Hrz3 is the adopter's step (rule R4).
- **Hrz4** AI-quality and model-risk gate: owns promotion. `eval/run_eval.py --mode gate`
  delegates the verdict through `agent_eval_kit.PromotionGateClient` under the bundle id
  `app-fraud-interdiction` and refuses to run off the managed profile; registering that bundle
  and its thresholds with Hrz4 is yours (P-08, rule R5).
- **Hrz5** observability and immutable WORM audit: `adapters/gcp/tracer.py` sends OTLP to the
  Hrz5 collector when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and to Cloud Trace when it is not.
  The audit half is local and tamper-evident today; pointing it at the shared sink is rule R2.
- **Hrz7** human-review and maker-checker console: every hold and block is ROUTED there over the
  shared `review-kit` in the same request that produced it (rule R8). You wire your
  endpoint (`HRZ_HUMAN_REVIEW_URL`) and the outbound `HRZ7_S2S_TOKEN` /
  `HRZ7_S2S_SIGNING_KEY` pair. You do not re-implement the console.
- **Rsk3** architecture and requirements validator: an intake action, not a code control. Record
  your validation reference in `COMPLIANCE.md` when the project passes it (rule R6).

Adjacent financial crime verticals are separate systems, not features to absorb here: **G1** AML
alert triage and SAR narrative, **G2** sanctions, PEP and payment-message screening, **G4**
account-takeover investigation, **G5** the SOC fraud-fusion copilot. G3's responsibility starts
at an in-flight payment and ends at a routed verdict with a cited warning; the case that follows
a confirmed scam belongs to those systems.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py` (preview, then `--yes`), recreated the venv, `make gate` green.
- [ ] Set the Terraform `region` AND `allowed_regions` and the application's `GCP_REGION` to your
      in-country region, and wired `terraform -chdir=infra/terraform test` into a build.
- [ ] Wired your IdP on the deployed service and set `SCAMINTERDICT_IAP_AUDIENCE` (or implemented
      the `onprem` identity adapter).
- [ ] Replaced every rule pack in `rulepacks/` with your own markets, instruments, thresholds and
      uplifts, reviewed and signed off by your policy owner.
- [ ] Replaced `rulepacks/scam_lexicon.yaml` with your fraud team's cues, in your locales.
- [ ] Set `JURISDICTIONS` in `domain/pii.py` for the markets you actually serve.
- [ ] Replaced every synthetic fixture (`adapters/local/_fixture_data.py`,
      `tests/fixtures/sample_cases.py`).
- [ ] Rebuilt `eval/datasets/golden_cases.jsonl` and reconciled `THRESHOLDS` with the per-market
      metric names your fork uses.
- [ ] Reviewed the deploy posture (Dockerfile, all of `infra/terraform/`, the bind address) and
      cleared `INCOMPLETE_MANAGED_OPERATIONS` before serving the managed profile.
- [ ] Wired your Hrz7 endpoint, decided which sibling systems you integrate vs stub, and bound a
      Hrz1 guardrail before any live model sees untrusted text.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
