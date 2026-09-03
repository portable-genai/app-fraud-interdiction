# Adoption FAQ

For an engineering lead forking this repo as their institution's scam and APP interdiction base.
The step-by-step is [`../ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?"
questions.

### How do I rebrand it for my organisation?

`scripts/rename_fork.py` rewrites four identifiers in one pass: the package name
`app_fraud_interdiction` (which is ALSO the console-script name), the `SCAMINTERDICT` environment
prefix, the distribution and resource id `app-fraud-interdiction`, and optionally the Terraform
`name_prefix` default `g3-svc`. Preview with `--dry-run`, apply with `--yes`, sweep Markdown prose
too with `--include-docs`. Then recreate the venv, `make install`, and run `make gate`. There is
no `--cli` flag (the console script is named after the package, so a second flag could only
drift) and no `--dist` flag (`--resource` is one literal doing four jobs: the distribution name,
the GitHub id, the A2A agent-card name and the Hrz4 eval bundle id, deliberately the same string
so a fork's promotion record and its discovery card cannot disagree). The script does the
mechanical rename; the human decisions are the checklist in `ADOPTING.md`.

### If several institutions fork this, how does each take upstream fixes?

Track upstream via git tags. The repo declares a core-vs-adopter-owned boundary
([`../ADOPTING.md`](../ADOPTING.md) section 2): upstream owns `domain/kernel.py`, the engine, the
rule-pack parser, the warning validator, `ports/`, `config.py`, `adapters/_review_payload.py`,
`tests/contract/` and the eval mechanics; you own everything in `rulepacks/`, the settings values,
the local fixtures, `adapters/onprem/*`, UI theming, the golden set and the jurisdiction rows in
`COMPLIANCE.md`. Rebase your adopter-owned changes onto each release rather than merging `main`
continuously, so conflicts stay in files you were told to expect.

### Is there a real kernel module I keep untouched?

Yes, and it is a physical split rather than a docstring convention. `domain/kernel.py` holds the
vertical-neutral machinery (`Citation`, `AuditEvent`, `RiskBand`, `Verdict`,
`CONSEQUENTIAL_VERDICTS`, `utcnow`) and imports nothing from this vertical;
`domain/models.py` holds only the G3 artifacts (`PaymentEvent`, `FeatureValue`, `FeatureVector`,
`ScamLexiconHit`, `ReasonCode`, `InterdictionAssessment`). A fork building a different
deterministic decision rewrites `models.py` and leaves `kernel.py`.
`tests/unit/test_core_purity.py` keeps the whole core honest about what it may import.

### Can I retune the policy numbers without touching code?

Entirely, and this is the part most forks care about. Every number is data in `rulepacks/*.yaml`:
the `baseline_score`, the verdict cutoffs (`warn`, `hold`, `block`), the band cutoffs (`medium`,
`high`, `critical`), and per rule the `feature`, `op`, `threshold`, `uplift` and the `locator`
that becomes the citation. `domain/interdiction_engine.py` contains no threshold literal and no
market branch; it reads them. A pack is validated at load
(`RulePack.from_mapping` plus `__post_init__`), so non-decreasing cutoffs, a duplicate rule code
or an unknown operator is refused at load time rather than discovered at scoring time. The
comparison operators are a closed set (`>=`, `>`, `<=`, `<`, `==`).

### How do I add a market?

Three edits and no engine change: a new `rulepacks/<market>.yaml` (its `market:` field must match
the key), a row in `MARKET_FILES` in `rulepacks_loader.py`, and a row in `_LOCALES` in
`domain/interdiction_service.py` so the warning is drafted in the right language. Then extend the
eval: `THRESHOLDS` in `eval/run_eval.py` carries a per-market `verdict_accuracy_<MARKET>` entry
and `_falsify` seeds a green/red pair per market, so a regression confined to one jurisdiction
cannot hide inside an aggregate. An unknown market is refused rather than guessed
(`test_an_unknown_market_is_refused_not_guessed`).

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list and the contract test enforces it in both directions. A port must be
registered in FIVE places or it runs with no enforcement at all: the `@runtime_checkable`
Protocol re-exported from `ports/__init__.py` with an entry in `PORT_PROTOCOLS`,
`config.DEFAULT_BINDINGS`, a `Container` accessor, the `adapters:` block in
`config/settings.yaml`, and a `PortCase` in `tests/contract/canonical.py`. Then bind it in all
three families. `tests/contract/test_port_parity.py` asserts set equality across all five, and
`tests/unit/test_settings_file.py` fails if `DEFAULT_BINDINGS` and the settings file disagree.
The file-by-file walkthrough is in [`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I add an adapter for an existing port?

One class under `adapters/<family>/` with the single constructor shape `Adapter(settings)`, cloud
imports INSIDE the method (never at module scope, so the other profiles still import the tree
with no SDK), the same `module:Class` target in both `config.DEFAULT_BINDINGS` and
`config/settings.yaml`, and any new variable added to `.env.example`. If it is a managed adapter
that is not yet a real integration, add it to `INCOMPLETE_MANAGED_OPERATIONS` in
`managed_readiness.py` so a `gcp` process refuses to start rather than serving a placeholder;
remove the entry when the operation executes for real and its integration test proves the
response mapping.

### How do I change the taxonomy?

`RiskBand` and `Verdict` are `LenientStrEnum`s from the commons, so a member IS its wire value
and serialized JSON carries the enum string. Adding a band or a verdict means editing
`domain/kernel.py`, and for a verdict also `CONSEQUENTIAL_VERDICTS`, the `_ACTION_WORD` map in
`domain/warning.py` (a warning must name the action the engine ordered) and
`RulePack.band_for` / `_verdict_for` if the new member needs a cutoff. That is deliberately more
work than adding a rule: the action vocabulary is the contract every surface and the review
console share.

### Will the demo rot after I diverge?

It is guarded from two directions. A demo step exists in exactly two places, `demo.STEPS` and
`walkthrough.CHECKS`, and `tests/unit/test_demo_surface.py` holds the two equal inside the
offline gate, so a narrated claim nobody verifies cannot exist. `make demo-selftest` runs the
whole eight-step arc headless and unattended, asserting at each step that the service actually
reached the state the narration claimed, and the demo has its own required workflow
(the hosted GitHub Actions check) alongside `make portability`, `make demo-static` and
`make docs-check`. Put the numbers a check reads in the step's `facts` dict, never only in
rendered prose: a check that parses prose breaks on a wording change. Do not move the demo into
`make gate`, which must stay fast and offline.

### Does the build work for my fork out of the box?

Yes. `make gate` is deliberately offline and credential-free: `ruff check`, `ruff format --check`,
`mypy src`, `pytest -m 'not integration'` and the eval smoke run, with no cloud SDK, no project
and no network. The CI workflow is a thin caller of the shared reusable hard-gate workflow pinned
to a TAG (never a branch) and references no organisation secrets, so a fork's build is green
immediately; you add credentials only when you wire the `gcp` profile. `make audit` (pip-audit
over both lockfiles) is the one step that needs a network, which is why it is separate locally
and a hard-failing job in CI. Note that the eval measures the REFERENCE rule packs and golden
cases until you rebuild them, which is an explicit adoption step rather than a silent pass.

### What must I not skip before running this on real payments?

Four things, in this order: replace every rule pack and the scam lexicon with numbers and phrases
your policy owner has signed off; set `JURISDICTIONS` in `domain/pii.py` for the markets you
serve; rebuild the golden set so the gate measures your rulebook; and clear
`INCOMPLETE_MANAGED_OPERATIONS` before serving the managed profile. The full list is the checklist
in [`../ADOPTING.md`](../ADOPTING.md) section 6, and the compliance view is in
[compliance-faq.md](compliance-faq.md).
