# FAQ index

Answers to the questions different teams ask when evaluating, adopting or reviewing this
repository (G3, Scam and APP Interdiction) as a common base for real-time scam and
authorised-push-payment interdiction. Each file is written for a specific audience; skim the one
that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec / security review | what is processed, server-side identity, the exposure guard, secrets, supply chain, the anchored audit chain, what is out of scope |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | the no-lock-in claim, the three profiles, the executable portability check, residency, data export |
| [features-faq.md](features-faq.md) | Product / financial crime / delivery | what the service produces, deterministic vs model, and the full "what this repo owns vs what it integrates" map |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | the rebrand, upstream fixes, rule packs, adding a market or a port, whether the demo rots |
| [compliance-faq.md](compliance-faq.md) | Compliance / model risk / privacy | maker-checker, PII handling, auditability, residency enforcement, the model-risk story, regulator crosswalk |

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the
catalog. Where a concern belongs to another repo (the guardrail gateway Hrz1, the knowledge base
Hrz2, the agent registry Hrz3, the AI-quality gate Hrz4, observability and WORM audit Hrz5, the
human-review console Hrz7, the intake validator Rsk3, or the adjacent financial crime verticals
G1, G2, G4 and G5), the FAQ names the owning catalog id and explains the boundary rather than
duplicating it. See [features-faq.md](features-faq.md) for the full map, and
[`../ADOPTING.md`](../ADOPTING.md) for the fork path.
