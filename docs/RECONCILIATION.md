# Reconciling PART 18 against the actual source tree

PART 18 of the master prompt describes moulding a named legal-assistance
codebase into SAMVEDNA, and instructs: *"When the source tree is available,
reconcile the file paths below against it before starting."*

This is that reconciliation, and its first finding is the important one.

## The codebase PART 18 assumes is not the codebase that exists

The prompt's reuse map was written against a repository that is not present in
this workspace and, on the owner's confirmation, is unrelated to this work. Its
component table therefore cannot be applied as written.

What follows replaces it: the same *idea* — reuse what transfers, build the risky
parts new — mapped onto what was actually available.

## The real ancestor was a clinical decision-support system

The workspace did contain an in-house system for clinical voice analysis, and it
turned out to be a markedly better ancestor than the one PART 18 assumed. Its
architecture already solved four of the problems SAMVEDNA has to solve:

| The ancestor already did | SAMVEDNA needs | What transferred |
|---|---|---|
| A **pure `domain/` package** with no I/O, tested by writing events | L3 must be interrogable by an auditor and testable in milliseconds | The discipline, enforced here by an AST test that fails on any I/O import in `core/` |
| **Event log as a fold**; replay reproduces exactly what a clinician saw | REPLAY mode (constraint 7) and a reproducible audit trail | Run records + the hash-chained ledger + `pipeline/replay.py` |
| **Graded reference bands**, weighted fusion, a corroboration floor, and `Evidence` naming the feature, its value and the band it left | Four gates that return every input term and a formula with numbers substituted | The gate arithmetic. `MIN_CONTRIBUTORS = 2` is the direct ancestor of the breadth requirement |
| **Ports as Protocols**; the engine never imports a concrete implementation | Seven record connectors, swappable between REPLAY and live | `ingest/ports.py` |
| **Degraded stages reported, never faked** | PART 8.8: every degradation makes the system say less | `ConnectorResult.status`, `ReviewerFinding.status`, `RiskAssessment.status` |
| Clinician **confirms/dismisses each finding**, and that shapes the report | Officer close-out (Stage 10) as the only honest precision measurement | `pipeline/outcomes.py` |

That system's thesis — *the model proposes, the clinician disposes* — is one step
short of SAMVEDNA's. SAMVEDNA replaces the human judgement at the *gate* with
arithmetic, because a name attached to a soldier needs a defence stronger than an
opinion, and keeps the human where the action is taken.

**That is the honest pitch line**, and it is stronger than the one PART 18
proposed: *"we reused our architectural patterns — pure domain core, ports and
adapters, event-log replay, evidence that carries its own numbers — and built the
decision engine and the disclosure layer from scratch."*

## What was NOT reused

**No code.** Not one import, path or file from any neighbouring project. Verified
by parsing every module in `src/` and enforced in `tools/portability_check.py`,
which fails the build on a neighbouring-project import, on a relative import
escaping the package, or on any path reaching outside the tree.

The requirement was that SAMVEDNA be an independent project rather than a
dependency, and it is: `./check.sh --transfer` unpacks the archive into a
directory with no relation to this one, installs cold, and runs the whole suite
there. What transferred was architecture — patterns a person carried from one
problem to another — not files.

*(This document names no neighbouring repository, deliberately. A recipient
opening this archive has no access to them, so naming them would be confusion at
the far end of a transfer rather than context.)*

## PART 18's row-by-row map, answered

| PART 18 said | Reality |
|---|---|
| React 18 · Vite · shadcn/ui → reuse as-is | **Next.js 15 + React 19**, written new. No Vite or shadcn in this tree to reuse |
| `RouteGuard` + role-based routing → extend to four roles | Built new in `disclosure/rbac.py`, and stronger: authorisation is a **(role, purpose)** pair, not a role |
| Managed-cloud auth context → re-host on Keycloak | Nothing to re-host. A REPLAY header shim stands where OIDC goes and **returns 501 outside REPLAY mode** |
| `LanguageContext` + i18n → vernacular consent screens | **Not done.** Honest gap — see below |
| Database row-level security → row isolation per pid/unit | Enforced in L5 rather than in the database, so a direct query cannot bypass it. SQLAlchemy models are the persistence seam |
| `violations` table → the audit ledger | Built new: append-only, hash-chained, with **no update/delete/amend method at all** |
| Edge Functions → Airflow stage workers | `pipeline/dag.py` — ten stages, each with its own timing, row counts and status, shaped so an Airflow task is a thin wrapper |
| Multi-agent orchestration → three reviewers | Built new in `analytics/reviewers/`, running in parallel with a freeze rule |
| Zod validation → Pydantic v2 | Frozen dataclasses with `__post_init__` validation; Pydantic on the API boundary |
| ChromaDB + MiniLM → intervention retrieval | **Lexical overlap, deliberately.** A nearest-neighbour result nobody can check is the wrong thing to hand an officer deciding whether to approach a person. The seam is a Protocol |
| Recharts → gate bars and heat maps | Hand-built SVG-free CSS bars. One fewer dependency, and the bar is not the point — the formula under it is |
| Payments, video consultation, free-text chat UI, external LLM APIs, managed cloud → drop | Nothing to drop. None of it exists here |

## Deviations from the master prompt, and why

Four, each argued rather than assumed.

**1. PART 6.65 row 8 prints 0.467; this build computes 0.000.** The published
figure puts the domain's own weight in the numerator — a domain corroborating
itself. Under that rule the *demo* row computes to 0.774 and **passes** the 0.700
threshold, destroying the single most defensible moment in the design. Excluding
self reproduces the demo row exactly (25/36 = 0.69444) and scores a lone
confounded domain 0, which is the honest answer. Same outcome as published
(fail); different displayed value.

**2. The consistency gate discounts commonly-caused corroboration.** As
published, three domains all explained by the same unit surge corroborate each
other at full strength — the ecological fallacy with a threshold attached. On the
synthetic force it escalated five people inside the one unit whose situation was
already explained. Fixed by discounting a supporting domain by its **unshared**
confounder mass. Every published calibration row still reproduces exactly.

**3. scikit-learn rather than LightGBM; no torch, Flower or Opacus.** The first
training run died with `Library not loaded: @rpath/libomp.dylib`. A project that
must survive being copied to a pendrive or emailed cannot carry a native
dependency the recipient has to go and install. The algorithms are the same
family, the contracts are the same (FedAvg over parameter vectors; discrete-time
hazard), and LightGBM remains an optional `fast` extra.

**4. A Next.js PWA rather than Flutter.** Flutter is not installed and the SDK
download would have delayed Phase 11 substantially. The PWA ships the whole of
Workflows A and B today; the Flutter port is a packaging exercise against the
same API.

## Voice concordance is an add-on, not core scope

The SIH submission names three input sources: service records, voluntary
self-report and an opt-in wearable. **Voice is a fourth, added afterwards at the
owner's request as a further way of understanding what a person is telling us.**

It is wired in as a full domain so it can corroborate a case, and tiered T3 so it
can do nothing more than that — a voice signal alone scores 0.183 against a 0.65
evidence threshold. There is deliberately no connector that could fetch a voice
overnight; it comes only from a sitting the person chose to start.

The interface labels it throughout: behind a divider in the navigation, tagged
`add-on`, and with a banner at the top of its own page stating that the core
system does not depend on it. That is not modesty — a reviewer holding the
submission should not have to work out which capabilities were promised and
which arrived later.

## Honest gaps

- **i18n / vernacular consent screens are built** (Phase 16). Eight languages
  cover the whole personnel surface, a missing key fails the build rather than
  falling back to English, consent is recorded against the exact text and version
  read, and an unreviewed translation is refused as a basis for consent. **Seven
  of the eight remain machine-drafted and are marked as such** — they are
  complete and structurally verified but have not been read by a native speaker,
  and the system will not record consent against them until they have been.
  Obtaining that review is procurement rather than engineering; the workflow that
  makes it a small, checkable task is what shipped.
- **Airflow, Keycloak, PostgreSQL + TimescaleDB and Kubernetes are seams, not
  deployments.** Neither Docker nor Postgres is available on the build machine.
  The stage shapes, the OIDC boundary and the SQLAlchemy models are written so
  each is a substitution rather than a rewrite, but none has been run against the
  real thing and that should not be claimed.
- **Subgroup fairness is under-measured on synthetic data.** Four subgroups have
  fewer than three positives and are reported as **NOT MEASURED** rather than
  scored. That is the correct handling, not a fix.
- **The survival and rhythm models are not surfaced in the console yet.** They
  are computed, tested and available through the API's case detail; the officer
  UI does not render horizons.
