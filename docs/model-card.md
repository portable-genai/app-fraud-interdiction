# Model card: Scam and APP Interdiction (G3)

This is a STARTER model card. It records the model boundary as built and the controls that must
be completed before a managed deployment. The deterministic engine is the system of record; the
model is a bounded, replaceable component that today has no live implementation at all.

## What the model does, and does not do

- **Does**: draft the customer-facing warning, and nothing else. `WarningGeneratorPort`
  (`ports/warning_generator.py`) is the one seam a model may touch. It receives a
  `WarningRequest` (`domain/warning.py`) carrying the already-computed verdict, the market, the
  citing instrument, the titles of the rules that fired and the closed set of `allowed_figures`,
  and it returns a plain string restating that decision in locale-aware customer language. The
  caller then judges the string.
- **Does NOT**: produce any number, band, verdict or escalation. The score, the fired
  `ReasonCode` set, the allow / warn / hold / block verdict, the `RiskBand` and the
  `requires_human_review` flag are all computed by `domain/interdiction_engine.py` in pure
  standard library, from the payment event, its `FeatureVector` and the market `RulePack`
  (`domain/rulepack.py`). That engine has no clock and no I/O: it reasons over `event.as_of`, and
  `signal_key` is a SHA-256 fingerprint of what drove the decision so two replays diff exactly.
  Every threshold and uplift lives in `rulepacks/*.yaml`, reviewed by a policy owner, never in a
  prompt. `tests/unit/test_interdiction_service.py::test_every_number_is_identical_whatever_the_generator_does`
  is the standing proof: swap the generator, and no figure moves.
- **Does NOT, today, exist as a live model.** The managed adapter
  (`adapters/gcp/warning_generator.py::VertexWarningGenerator.draft`) lazily imports the model
  SDK and then raises `NotImplementedError`. It is a construction seam, not an integration. The
  fail-closed preflight in `managed_readiness.py` lists
  `warning_generator.VertexWarningGenerator.draft` in `INCOMPLETE_MANAGED_OPERATIONS`, so a `gcp`
  process REFUSES to start while it is bound (`tests/unit/test_managed_readiness.py`). Everything
  the repo runs today runs on the deterministic offline generator.

## Boundary and validation

- **Redaction before anything leaves.** PII is masked with the shared `pii-kit` before the WORM
  audit write (`domain/interdiction_service.assess`, using the row selection and order in
  `domain/pii.py`), before the review payload reaches Hrz7 (`adapters/_review_payload.py`, against
  every jurisdiction's rows because the console is a shared sink), and before a tool result can
  enter a model's context (`agent/tools.py::_redacted`, which walks the whole structure rather
  than three named fields). `tests/unit/test_interdiction_service.py::test_pii_in_the_memo_is_redacted_before_the_audit_write`
  proves the audit half; the eval's `pii_safety` metric scores it two independent ways, a pack
  scan plus a planted-literal oracle, and `tests/unit/test_not_falsely_green.py::test_pii_safety_can_go_red`
  proves that metric can fail. Note the honest limit: the `WarningRequest` handed to the
  generator is built from the engine's own output (verdict, instrument, rule titles, figures) and
  carries no customer memo, payer or payee reference, so the model seam is minimised by
  construction rather than by a redaction step of its own.
- **What validates the model's output.** `domain/warning.validate_warning` is the gate a draft
  must pass. It is length-capped at `MAX_WARNING_CHARS` (480), it must name the action the engine
  ordered (`allowed`, `warning`, `hold`, `blocked`), and every digit run in it must appear in
  `request.allowed_figures`. A draft that invents a number, runs long, is empty, or does not
  describe this decision is discarded.
- **What happens to a bad output.** It is replaced, never repaired. The orchestrator falls back
  to `domain/warning.build_fallback_warning`, a pure deterministic pack-cited template that is
  always available and always grounded, and stamps `warning_source="fallback"` on the assessment
  so a reader can tell the two apart. A generator that raises is caught and treated the same way,
  so an interdiction never waits on generation.
  `test_a_failing_generator_falls_back_to_the_deterministic_template` and
  `test_a_generator_that_invents_a_figure_is_discarded` are the standing gates, and the eval's
  `warning_groundedness` metric (threshold 0.99) scores the same property over the golden set.
- **R8 human-review routing.** A `HOLD` or a `BLOCK` is consequential
  (`domain/kernel.CONSEQUENTIAL_VERDICTS`); it sets `requires_human_review` AND is routed through
  `ReviewRouterPort` to the Hrz7 console in the same call that produced it, on all three surfaces
  (`api/app.py`, `cli/main.py`, `agent/tools.py`). A `BLOCK` demands two approvals. Nothing
  auto-executes, and the model has no way to reach this path: it never sees the verdict until
  after the verdict exists. `tests/unit/test_review_routing.py` asserts the routing rather than
  the flag.

## Adapters and profiles

| Profile | Warning generator adapter | Behaviour |
|---|---|---|
| `local` | `adapters/local/warning_generator.py::LocalWarningGenerator` | Deterministic, template-shaped, SDK-free. Restates the verdict and the fired rule titles, invents no figure, so it passes validation and the demo shows a "model" warning with no cloud call. Deliberately distinct from the fallback, so the fallback path stays independently testable. |
| `gcp` | `adapters/gcp/warning_generator.py::VertexWarningGenerator` | Lazy SDK import, then `NotImplementedError`. No model id, no prompt, no endpoint. Listed in `managed_readiness.INCOMPLETE_MANAGED_OPERATIONS`, so a managed process refuses to start with it bound. |
| `onprem` | `adapters/onprem/warning_generator.py::OnPremWarningGenerator` | Fail-fast placeholder for a client-hosted model, the reversibility proof (P-12). It raises rather than pretending. |

**The speech side.** `ports/speech.py` re-exports the `speech-lexicon-kit` STT, TTS and
diarization protocols and the `Transcript` / `SpeakerTurn` value types so consumers have one
import site for the speech boundary, but this repo binds NONE of them in its container: they are
not in `PORT_PROTOCOLS`. What the repo actually binds is `ConversationChannelPort`, which returns
an already-diarized transcript. Under `local` that transcript is scripted fixture data
(`adapters/local/_fixture_data.py`); under `gcp` the adapter is another construction-only
placeholder (`conversation_channel.CcaiConversationChannel.fetch`, also in
`INCOMPLETE_MANAGED_OPERATIONS`). So today this system performs **no speech recognition, no
speaker diarization and no speech synthesis**: no audio is transcribed, no spoken warning is
produced, and no voice biometric or emotion inference of any kind is attempted. What runs over a
transcript is deterministic phrase matching: `domain/scam_lexicon.scan` calls the kernel's
`find_hits` over the customer's turns only, against the adopter-owned phrase pack
`rulepacks/scam_lexicon.yaml`, and folds the count of distinct entries into the single numeric
feature `scam_call_lexicon_hits` that the engine thresholds like any other. A hit is a FEATURE,
never a verdict; a call in a language the pack does not cover yields zero hits rather than
failing the interdiction. Anyone adding real STT here inherits a new personal-data boundary
(raw audio and a raw transcript) that today does not exist, and must add redaction and retention
controls for it.

## Remaining controls (TODO, repo owner)

- **A model at all, then its id, version and routing** (P-07, P-11). There is no live generation
  path yet. When one is wired: implement `VertexWarningGenerator.draft` against a real endpoint,
  add its integration test, remove the entry from `INCOMPLETE_MANAGED_OPERATIONS`, pin the exact
  model and prompt version, and record both here. Hrz4 keys a promotion to the exact model that
  produced the evidence, so a silent model swap invalidates the old verdict.
- **Budget, rate controls and a kill switch** (P-10, P-11). Per-tenant token budget, a request
  rate limit, a timeout and circuit breaker on the generation call, and a switch that forces
  deterministic-only operation with the model disabled. The deterministic floor already exists
  (`build_fallback_warning`), so the kill switch is a binding change rather than a new code path;
  it is not wired or documented today. Report spend through Hrz5.
- **A managed-profile eval run through the Hrz4 gate** (P-08, rule R5). The offline eval scores
  the deterministic offline generator, not a model: `warning_groundedness` currently measures a
  template that cannot hallucinate. `--mode gate` delegates to Hrz4 under the bundle id
  `app-fraud-interdiction`, but that bundle and its thresholds are not registered yet, so gate
  mode has no authority to ask. Register it, then score real drafts against the same golden
  cases.
- **Prompt-injection screening through Hrz1** (rule R1). No `GuardrailPort` exists. The customer
  memo and the call transcript are attacker-influenceable text; today neither reaches a model,
  which is why the gap is survivable, and the moment one does the screen must be in front of it,
  failing closed to deterministic-only when the screen is unavailable.
- **Grounding through Hrz2** (P-05, rule R3). There is no retrieval port, so there is nothing to
  ground and the row is honestly open rather than quietly claimed.

Until these are complete the system is safe to run offline: the deterministic engine plus the
template generator, with every consequential verdict computed in pure stdlib, every warning
grounded in the engine's own figures, every audit record redacted, and every hold and block
routed to a human. The managed model path is not production-cleared, and the repo enforces that
rather than trusting it: a `gcp` process will not start while the placeholder is bound.
