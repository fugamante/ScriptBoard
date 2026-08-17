# Lightweight Engineering Plan

Baseline date: 2026-08-05  
Owner role: ScriptBoard maintainer  
Next review: 2026-11-03  
Profile: lightweight with elevated privacy controls for live-provider use

This is the combined control artifact for the IEEE 730, 828, 829, 830, 1016,
1012, and 1058 families. It does not assert certification or formal compliance.

## Purpose, requirements, and management — IEEE 830 and 1058 families

ScriptBoard turns local screenplay drafts into storyboard prompt packs,
resumable image-job ledgers, local image files, panel catalogs, and a local HTML
review board.

In scope:

- local CLI execution against an operator-selected project directory;
- Final Draft, plain-text, and Markdown inputs;
- deterministic fake-provider validation and explicit real-provider execution;
- resumable local ledgers and locally retained generated assets;
- sanitized plan, dry-run, revision, and failure output.

Out of scope without reassessment:

- hosted, unattended, scheduled, bulk, or multi-user operation;
- central storage of screenplay content, prompts, credentials, or images;
- a claim that provider output is safe, accurate, or production-approved;
- automatic retry of failed or moderation-blocked prompts without explicit
  operator intent.

Acceptance criteria:

- `python3 -m unittest` passes.
- `python3 -m py_compile scriptboard/*.py storyboard_tool/*.py` passes.
- Real generation is preceded by sanitized plan or dry-run and exact-job review.
- Credentials remain environment-only and private artifacts remain outside the
  reusable repository.
- Provider metadata and errors cannot persist API keys, signed URLs, raw prompt
  text, revised prompt text, or screenplay passages.

Next milestone: keep the standalone tool reliable while deciding whether any
supported release or additional provider lane is justified.

## Design — IEEE 1016 family

- `scriptboard.cli` owns command routing and explicit mutation boundaries.
- Builder/config modules convert selected local drafts into prompt artifacts.
- The job ledger is the durable source of truth for pending, running, done, and
  failed provider work.
- Provider adapters receive a selected job and return image bytes plus
  sanitized metadata; final files are written locally before completion.
- The fake provider is the deterministic validation boundary.
- `storyboard_tool` is a compatibility package and must not diverge silently
  from the maintained `scriptboard` behavior.
- `docs/IMAGE_PROVIDERS.md` is the detailed provider and ledger design source.

## Configuration management — IEEE 828 family

- Git-tracked source, tests, docs, `pyproject.toml`, and this assurance baseline
  are controlled items.
- Generated storyboards, images, private revisions, credentials, build output,
  and environment files remain ignored and outside release artifacts.
- Version changes update `pyproject.toml` and any affected interface docs.
- Ledger or revision schema changes retain explicit `schema_version` handling,
  tests, and compatibility notes.
- Before real provider mutation, use a plan or dry-run; recovery relies on
  resumable ledger state, existing-file reconciliation, checksums, and explicit
  retry intent.

## Testing and V&V — IEEE 829 and 1012 families

Required evidence for normal changes:

- unit tests for draft selection, configuration, ledger transitions, CLI paths,
  cleanup, board/catalog generation, and fake-provider behavior;
- negative privacy tests for plan/revision output, persisted provider metadata,
  provider failures, signed URLs, keys, prompts, and screenplay passages;
- syntax compilation for both packages;
- manual review of documentation links and the exact command behavior changed.

Live-provider change evidence additionally requires:

- fake-provider tests first;
- sanitized `plan` and `generate --dry-run` review;
- an exact synthetic job for any paid/network smoke;
- no secrets or private screenplay content in retained logs;
- human acceptance of the selected job and residual provider risk.

V&V independence decision: the lightweight local scope does not require a
separate approver. A second reviewer is required before a supported release that
changes credential handling, redaction, provider metadata, private prompt flow,
or default mutation behavior. Hosted or unattended operation requires a new
high-assurance decision before implementation or use.

## Quality assurance — IEEE 730 family

Quality gate: relevant tests and syntax checks pass, privacy-negative cases stay
covered, changed public behavior is documented, and skipped checks plus residual
risk are reported.

The ScriptBoard maintainer may accept normal lightweight changes. Privacy or
credential-control exceptions require explicit project-owner authorization with
compensating evidence and an expiry date.

## Risks and responses

| Risk | Current response | Status / escalation |
| --- | --- | --- |
| Private prompt disclosure to logs or ledgers | Sanitized previews, allowlisted metadata, redacted errors, negative tests | Controlled; escalate on any leakage |
| Credential disclosure | Environment-only key; ignored local environment file; no persisted key fields | Controlled; escalate on new credential source or provider |
| Wrong or repeated paid generation | Plan, dry-run, exact-job selection, explicit retry, resumable state | Controlled for operator-invoked use |
| Browser/auth-state fragility | Browser automation remains an optional legacy fallback | Reassess if it becomes a primary path |
| Unattended or hosted use | Outside approved lightweight scope | High-assurance reassessment required before use |
| Private consumer artifacts entering this repository | Documented boundary and ignore rules | Stop publication; remove safely and review exposure |

## Freshness and acceptance record

- Accepted on: 2026-08-05.
- Baseline evidence: `python3 -m unittest` passed 31 tests and
  `python3 -m py_compile scriptboard/*.py storyboard_tool/*.py` passed on
  2026-08-05.
- Release-readiness evidence: `python3 scripts/install_smoke.py`,
  `python3 -m unittest` (31 tests), package syntax compilation including
  `scripts/install_smoke.py`, CLI help checks, `git diff --check`, and focused
  privacy scans passed on 2026-08-17.
- Retention: tracked controls and tests in Git; concise pass/fail results in the
  change/release record; private prompts and outputs are not assurance records.
- Revisit no later than: 2026-11-03.
- Revisit immediately for new providers, schema changes, hosted/unattended/bulk
  execution, persistent remote state, multi-user access, privacy or credential
  incidents, changed defaults, supported release commitments, or ownership
  change.
