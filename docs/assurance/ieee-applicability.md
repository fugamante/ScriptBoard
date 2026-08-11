# IEEE Control Applicability

Status: accepted lightweight baseline  
Assessed on: 2026-08-05  
Next scheduled review: 2026-11-03  
Owner role: ScriptBoard maintainer  
Decision authority: project owner direction dated 2026-08-05

This record describes tailored engineering controls. It does not claim IEEE
certification, formal compliance, or audited assurance.

## Profile decision

Selected profile: `lightweight`.

ScriptBoard is a small, standalone, operator-invoked developer tool with a
compact dependency-free Python package, one test module, deterministic fake
provider support, and no hosted service or production release commitment. Its
repository boundary permits only reusable tooling and synthetic fixtures.

The live-provider lane crosses credential and private-prompt boundaries. That
lane therefore receives elevated privacy and V&V controls inside the combined
plan: explicit review and dry-run, exact-job selection, environment-only
credentials, allowlisted metadata, prompt/error redaction, deterministic fake
provider tests, and local-only generated artifacts. This decision expires or
escalates before any hosted, unattended, scheduled, bulk, or multi-user use.

## Risk and lifecycle screen

| Signal | Result | Evidence or disposition |
| --- | --- | --- |
| External users or production operation | No current evidence | CLI is locally invoked; reassess before distribution with support or service commitments. |
| Persistent or sensitive data | Conditional | Consumer projects may contain private screenplay text and images; they remain outside this repository and require the elevated live-provider lane. |
| Secrets, privileged action, or security boundary | Yes, scoped | `OPENAI_API_KEY` is environment-only; provider execution is explicit and exact-job targeting is supported. |
| Material safety, financial, privacy, or operational impact | Privacy uncertainty | Prompt disclosure is the primary risk; current controls minimize persistence and output exposure. |
| Binding assurance obligation | No evidence | Reassess if customer, legal, contractual, or platform obligations appear. |
| Hard-to-reverse or destructive action | Limited | Generation writes local images and ledger state; dry-run and resumability reduce selection/recovery risk. |
| Shared interface or release commitment | Limited | CLI and ledger schema are maintained interfaces but no formal support commitment was found. |
| Legacy, supplier, or reused-component risk | Conditional | External image providers and the optional browser fallback require review when changed. |

## Family decisions

| Family | Decision | Artifact and current evidence | Owner role | Acceptance criterion | Revisit trigger |
| --- | --- | --- | --- | --- | --- |
| IEEE 730 | Integrated | `engineering-plan.md`; `python3 -m unittest` passed 31 tests on 2026-08-05 | ScriptBoard maintainer | Required checks pass; privacy boundary and anomalies are explicit | Failed test, provider/privacy incident, or changed quality gate |
| IEEE 828 | Integrated | `engineering-plan.md`; `.gitignore`; `pyproject.toml` | ScriptBoard maintainer | Source, generated artifacts, credentials, versions, and recovery rules are identifiable | Package, schema, artifact, dependency, or release change |
| IEEE 829 / ISO/IEC/IEEE 29119 | Integrated | `tests/test_scriptboard.py`; `docs/IMAGE_PROVIDERS.md` | Test owner | Unit suite passes and provider/privacy paths retain negative coverage | New provider, command, ledger field, failure state, or test gap |
| IEEE 830 / ISO/IEC/IEEE 29148 | Integrated | `README.md`; `docs/INTEGRATION.md`; `engineering-plan.md` | Product owner | Intended use, constraints, privacy boundary, and acceptance criteria are reviewable | New user class, hosted use, changed output, or behavior commitment |
| IEEE 1016 | Integrated | `docs/IMAGE_PROVIDERS.md`; `docs/INTEGRATION.md` | Design owner | Provider, ledger, CLI, filesystem, and privacy boundaries remain coherent | New provider architecture, remote state, schema, or browser dependency |
| IEEE 1012 | Integrated with elevated live-provider controls | Tests for dry-run, exact targeting, redaction, metadata allowlisting, retries, and resume | V&V reviewer | Intended-use checks pass; real-provider promotion requires human review and fake-provider evidence | Privacy incident, unattended operation, or inability to reproduce evidence |
| IEEE 1058 / ISO/IEC/IEEE 16326 | Integrated | `engineering-plan.md`; repository issue/change history | ScriptBoard maintainer | Scope, role, next milestone, risks, and review date are current | Ownership, lifecycle, release, dependency, or scope change |

## Acceptance evidence and freshness

- Baseline: repository state assessed on 2026-08-05.
- Accepted test evidence: `python3 -m unittest`, 31 tests passed on 2026-08-05.
- Evidence retention: plans and tests in Git; validation result in the change or
  release report when one is created. Do not commit private prompt/output logs.
- Scheduled freshness: 2026-11-03, earlier than the lightweight maximum because
  the live-provider privacy boundary remains material.
- Status: current for the standalone/local scope; not approval for hosted,
  unattended, bulk, scheduled, or multi-user operation.

## Exceptions

None. The elevated provider lane is a tailored control, not an omission. Any
future lowering requires explicit authorization, owner, rationale, compensating
evidence, approval date, expiry, and revisit trigger.

