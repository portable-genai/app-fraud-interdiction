# Security FAQ

For an AppSec reviewer sizing up this repo. It explains what the attack surface is, what is
deliberately out of scope (and why that is honest, not a gap), and where the evidence lives.
Cross-references: [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`../../COMPLIANCE.md`](../../COMPLIANCE.md), [`../runbook.md`](../runbook.md).

## What does this system actually process?

One in-flight payment at a time: an event id, an event timestamp, a market code, opaque payer
and payee references (tokenised upstream), an amount in integer minor units, a currency, a
channel, a free-text customer **memo**, and optionally a reference to a linked call whose
already-diarized transcript is fetched through `ConversationChannelPort`. So unlike a pure
aggregate-data service, this one DOES touch attacker-influenceable and potentially personal text:
the memo and the transcript. That is why redaction is unconditional rather than conditional, and
why the model seam is kept as narrow as it is.

## Where is personal data masked, and is that proven?

At every boundary, not once. Before the WORM audit write (`domain/interdiction_service.assess`,
using the row selection and order in `domain/pii.py`), before the review payload leaves the
process (`adapters/_review_payload.py`, scrubbed against EVERY jurisdiction's rows because the
`human-review-console` is a shared sink, and including the event id itself before it becomes the subject,
the case reference or the idempotency key), and before a tool result can enter a model's context
(`agent/tools.py::_redacted`, which walks the whole result structure rather than three named
fields, so a future field cannot arrive unmasked). Proven by
`tests/unit/test_interdiction_service.py::test_pii_in_the_memo_is_redacted_before_the_audit_write`,
by `tests/unit/test_review_routing.py::test_the_payload_is_redacted_before_it_leaves_the_process`,
and by the eval's `pii_safety` metric scored two independent ways (a `pii-kit` scan plus a
planted-literal oracle), whose ability to go red is itself asserted in
`tests/unit/test_not_falsely_green.py`. Note the deliberate asymmetry: an API response returns to
the authenticated caller the text that caller just submitted and is NOT masked; a tool result
becomes a model's context and is.

## How is identity handled? Can a caller spoof the actor?

No. `api/schemas.py::InterdictRequest` carries no `actor` and no `tenant` field at all, so there
is nothing to spoof in the body. The route depends on `get_principal`, which resolves a verified
`Principal` server-side through the bound `IdentityPort`, and that principal is what becomes the
audit actor and the `human-review-console` maker. Under `gcp`, `adapters/gcp/identity.py` verifies the IAP-injected
assertion with an explicit `audience=` (the configured `SCAMINTERDICT_IAP_AUDIENCE`) and IAP's own
`certs_url=`, and checks the issuer itself, because `verify_token` does not; an unset or emptied
audience REFUSES rather than verifying nothing. Under `local` the personas are seeded dev
identities resolved from `X-Dev-Persona`, and that adapter refuses to construct unless the local
profile was chosen deliberately. Under `onprem` it is a placeholder that raises.
`tests/unit/test_iap_identity.py` runs in every gate and `tests/unit/test_iap_crypto_matrix.py`
drives the REAL verifier over locally minted assertions.

## What stops the service serving a stranger when it is misconfigured?

Two independent mechanisms. First, the profile resolves ONCE at import into a `ProfileChoice`
with three states: unset is NO CHOICE (not a silent `local`), set-and-empty raises, and an
unknown or mis-capitalised value raises, both before the process can serve anything. Second, the
loopback exposure guard is bound at MODULE scope in `api/app.py`, so it holds under
`uvicorn ...:app` and the container `CMD`, not only under `main()`
(`tests/unit/test_serving_path_exposure.py`). Its posture is derived from the identity BINDING
and from nothing else: an adapter declares `VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED`
(`ports/identity.py`), and `SCAMINTERDICT_S2S_TOKEN` may never enter that decision, because it
authenticates a calling SERVICE and no end user. `tests/unit/test_end_user_auth_posture.py` walks
the guard's argument through the constants it names and fails the build if a credential reappears
at any depth. Interactive docs (`/docs`, `/redoc`, `/openapi.json`) are ABSENT rather than
guarded outside the deliberate `local` posture, because a guard the profile has switched off is
no guard.

## Are environment variables read safely?

Three states, everywhere, enforced by a test rather than by discipline. Unset, set-and-empty and
set-and-valid are different, and a variable an operator deliberately emptied never inherits the
more permissive unset default. `tests/unit/test_three_state_env_reads.py` walks the AST of
`src/`, `scripts/` and `eval/` and fails the build on any two-state `os.environ.get` /
`os.getenv` read that is neither an exact-match comparison against a literal nor exempted with a
written reason; `ui/tests/three-state-env-reads.test.mjs` applies the same rule to every shipped
`.mjs`, `.ts` and `.tsx`. Only `config.py` may read `SCAMINTERDICT_PROFILE`, held by
`tests/unit/test_profile_single_source.py`.

## What about outbound service-to-service calls?

The real one is the `human-review-console` review submission (`adapters/gcp/review_router.py`), built on the shared
`review-kit`, which is pure stdlib `urllib` with S2S headers wire-compatible with
`hex-service-kit`'s server verifier. Its credentials are the OUTBOUND pair `HUMAN_REVIEW_S2S_TOKEN` /
`HUMAN_REVIEW_S2S_SIGNING_KEY`, deliberately distinct variables from this service's own INBOUND
`SCAMINTERDICT_S2S_TOKEN`, so one leaking never grants the other. The `model-quality-gate` promotion client
(`adapters/gcp/evaluation.py`) is the other, built on `agent-eval-kit`. The managed review router
refuses to run with no console configured rather than swallowing an escalation.

## Are there secrets in the repo?

No literal secret material. `config/settings.yaml` holds only `${VAR}` and `${VAR:-default}`
interpolation tokens and non-secret defaults; `.env.example` documents every non-secret variable;
`.env.secrets.example` documents the secret NAMES with placeholder values. The IAP audience is
read at adapter construction and never logged.

## What is the supply-chain posture?

Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`, py3.12) installed with
`--no-deps` by `make install`, by CI and by the Dockerfile, so nothing ships from an uncommitted
resolve. The five commons packages (`pii-kit`, `hex-service-kit`, `agent-eval-kit`,
`review-kit`, `speech-lexicon-kit`) are declared by tag in `pyproject.toml` and pinned in
the lockfiles to the 40-character COMMIT each tag resolved to, because a tag can be moved and a
commit cannot; `tests/unit/test_repo_artifacts.py` asserts that three-way agreement offline.
`ruff` is pinned exactly, the base image is digest-pinned and runs non-root, Actions are
SHA-pinned, dependabot runs per ecosystem, and `pip-audit` (`make audit`) plus `npm audit` are
hard CI failures rather than advisories.

## Is the audit trail tamper-evident?

Yes, within honest limits, and further than a plain hash chain. The local sink wraps
`hex_service_kit.audit.HashChainedAuditLog`: SHA-256 chaining, `UPDATE` / `DELETE` triggers, JSONL
export and restore, and `verify_chain()`. On top of that, `audit_anchor_path` writes the chain
head to a file on a DIFFERENT volume on every append, because a truncated tail leaves a shorter
chain that verifies perfectly and only an external anchor catches it. Once the store and the
anchor disagree the service refuses to append rather than re-anchoring, so an ordinary write
cannot launder a divergence. `tests/unit/test_audit_anchor.py` proves both halves including the
control case that fails without the anchor. This is not a substitute for the managed WORM sink in
production: that is the locked Cloud Logging bucket (`infra/terraform/logging_worm.tf`) and,
enterprise-wide, `agent-observability`.

## What is explicitly out of scope for this repo?

The prompt-injection and output-screening engine (`agent-guardrail-gateway`, and note it is NOT bound yet, which
`COMPLIANCE.md` rule R1 states plainly), the governed knowledge base (`enterprise-knowledge-base`), the agent
registry (`agent-registry`), the AI-quality and promotion gate (`model-quality-gate`), the enterprise WORM audit and
tracing sink (`agent-observability`), the human-review console (`human-review-console`), and the intake architecture
validator (`architecture-validator`). This repo integrates those through ports rather than re-implementing them.
Speech recognition is also out of scope: `ports/speech.py` re-exports the kernel's STT, TTS and
diarization protocols for one import site, but none of them is bound in the container, so no
audio is processed here. See [features-faq.md](features-faq.md) for the full boundary map and
[`../model-card.md`](../model-card.md) for the model boundary.
