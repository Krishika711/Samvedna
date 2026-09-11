# Agent handoff brief — SAMVEDNA

You are picking up SAMVEDNA, a working system built for Smart India Hackathon
2026, problem statement **PS 26186** — AI-based predictive personnel stress and
welfare monitoring for uniformed forces (CAPF and Armed Forces). Team CodeZila.

Read `README.md` for how to run it, `TRANSFER.md` if it arrived by email, and
`docs/CONTEXT_PHASES.md` for where the work stands. This brief tells you the things those documents cannot: what the
system *is for*, what will break if you touch it carelessly, and which of your
instincts will be wrong here.

## The one-sentence version

The system reads records the organisation already holds, plus voluntary
self-assessment, and decides whether a welfare concern is strong enough to put
in front of a human being. **The product is the refusal, not the prediction.**

## The claim the whole design defends

> A risk score is not a decision. Nothing reaches a human until the evidence
> earns it.

A model produces a suspicion. Four deterministic gates decide whether that
suspicion is allowed to become a name on an officer's screen. If any gate fails,
the system emits **no name** — only a MONITOR record and a machine-computed
statement of what additional evidence would have changed its mind.

This matters because the failure mode of every system in this category is the
same: it flags too many people, officers stop trusting it, and personnel learn
that answering honestly gets them watched. Gates exist to make the system shut
up.

## Invariants. Breaking any of these breaks the project

These are enforced by tests. If a test fails after your change, the test is
almost certainly right and your change is almost certainly wrong.

1. **No model, LLM or heuristic may emit a gate value, a verdict, or a
   confidence.** Models produce features and a risk score. Arithmetic in
   `src/samvedna/core/gates.py` produces decisions. There is no LLM anywhere in
   the decision path and there must never be one.

2. **`core/` is pure.** No I/O, no clock, no `random`, no `numpy`, no
   `samvedna.*` import outside `core` and `config`. A test parses every module
   in `core/` with the `ast` module and fails the build on a forbidden import.
   This is what makes the decision layer auditable and replayable.

3. **Actionability is multiplicative, never a weighted sum.** Its factors are
   hard vetoes — no consent, no available intervention, wrong authority. A
   weighted sum lets a strong score outvote a missing consent, which is exactly
   the bug the gate exists to prevent. See `gates.py`.

4. **Verdict precedence is fixed**: consent → actionability → persistence →
   evidence/consistency → ESCALATE. Do not reorder it for convenience.

5. **The safety override bypasses the gates.** An acute self-disclosure (PHQ-9
   item 9) routes straight to a mental-health authority with an SLA measured
   from submission time. It does not wait for a persistence window. If you find
   yourself making the override respect a gate, stop.

6. **Mind-change text is computed by inverting the failed gate.** It is never
   generated. That is why it can be trusted: it is the threshold arithmetic run
   backwards, so it cannot describe a route that would not in fact clear the
   gate.

7. **Domain tiers are config, never model-assigned.** T1/T2/T3 at weights
   1.00/0.70/0.40, fixed in `config/weights.py`. A test parses `core/` and fails
   on any policy number that escaped into it.

8. **A commanding officer never sees an individual.** Aggregates only, k≥5,
   suppressed rather than rounded, and the self-report, biometric and voice
   domains are withheld from command at any group size. This is not a
   configuration choice; it is why personnel answer honestly.

9. **The refused list is auditor-only.** An officer handed a "nearly flagged"
   queue would work it, which lowers the threshold to zero and undoes the
   refusal. `/api/refused` returns 403 to a welfare officer on purpose.

10. **Identity storage fails closed.** There is no configuration in which
    `db/store.py` writes an identity in the clear — a missing key, a
    development key provider in live mode, an in-tree or 0644 keyfile, or a
    missing crypto library all refuse. If you find yourself adding a plaintext
    fallback "just for the demo", the demo already has one: the in-memory
    directory of synthetic identities.

11. **Never put binary data through a text operation.** `bytes` has all of
    `str`'s tidying methods and they corrupt key material — one line of
    `read_bytes().strip()` silently mangled 1 encryption key in 21.
    `tests/core/test_binary_discipline.py` walks the AST and will name your
    file and line.

12. **`check.sh` must be able to fail.** `set -o pipefail` does not cross a
    process boundary, so inline blocks go through `block()`
    (`bash -uo pipefail -c`), never a bare `bash -c`, and no command's exit
    status is piped into `grep` or `tail`. Enforced by
    `tests/core/test_shell_discipline.py`.

13. **No PII, no organisation names, no absolute home paths, no external LLM
    endpoints, anywhere in the tree.** `tools/portability_check.py` fails the
    build on these. The system must transfer by pendrive and by email
    attachment; that constraint is a hard requirement, not a nicety.

## Four mistakes that were actually made here. Do not repeat them

These cost real debugging time. They are all the same shape: a number that
looked right and was not.

1. **A baseline that contained the window it was scoring.** A 60-day surge sat
   inside its own 180-day trailing mean, so `z_self` came out at 0.83 against a
   threshold of 2.0 and the surge was invisible. Fixed with
   `BASELINE_LAG_DAYS = 90`. Op-tempo cohort fractions went from 12% to 48–68%
   — that is how badly it was wrong. **If a deviation figure looks
   suspiciously calm, check what the baseline window includes.**

2. **The consistency gate committed an ecological fallacy.** Three domains all
   explained by the same unit-wide surge corroborated each other at full
   strength, scoring 1.000, and escalated five people whose only problem was
   that their unit was deployed. Fixed by discounting corroboration by unshared
   confounder mass *and* dividing by available support rather than by agreement
   alone. **Corroboration from a common cause is not corroboration.**

3. **An empty `Ledger` was falsy.** It defined `__len__` but not `__bool__`, so
   `ledger or Ledger()` silently discarded the caller's ledger and nine audit
   entries went into an object nobody could see. Fixed with `__bool__`.
   **In this codebase, a container with `__len__` needs `__bool__`.**

4. **Refreshing a differentially-private view was an averaging attack.** Fresh
   noise on every refresh averages back to the truth. Fixed with a release
   cache in `disclosure/dpcache.py` — a repeated view is served from cache and
   charged once. **Noise without a release cache is not privacy.**

And one that is not a bug but will waste your afternoon:

5. **`npm run build` while `npm run dev` is live renders the console
   completely unstyled.** They share `.next`. The page returns 200 and the
   stylesheet 404s, which looks exactly like a broken design. That is why
   `next.config.js` uses `distDir: process.env.NEXT_DIST_DIR` and `check.sh`
   builds into `.next-check`. **Check the stylesheet's status, not the page's.**

## Deliberate technology choices that look like mistakes

Do not "upgrade" these. Each one was chosen against a better-performing
alternative for the same reason: the system must run from a copied folder on a
machine with no network.

| Not used | Used instead | Why |
|---|---|---|
| LightGBM | `sklearn.GradientBoostingClassifier` + TreeSHAP | LightGBM needs `libomp`, a Homebrew native dependency. It breaks the copy. |
| Temporal Transformer | Discrete-time hazard model + explicit roster-rhythm features | `torch` is ~2 GB. It cannot be emailed. |
| A speech model | numpy-only DSP (autocorrelation F0, jitter, shimmer, HNR) | No model download, no network, and the six features are defensible individually. |
| A webfont CDN | System font stacks | A CDN link fails silently in an air-gapped data centre and announces the deployment to a third party in one that is not. |
| Postgres | In-memory + fixtures, REPLAY mode by default | No demonstration may depend on live service-record access. |

## Where things are

```
src/samvedna/
  core/        L3 — gates, verdict, mind-change, confounders. PURE. The product.
  config/      Every threshold, weight and tier. Nothing policy-shaped elsewhere.
  analytics/   L2 — feature store, risk models, attribution, the reviewer panel
  ingest/      L1 — connectors, pseudonymisation, the synthetic force generator
  disclosure/  L5 — RBAC, k-anonymity, DP + release cache. Only layer that re-identifies.
  pipeline/    L4 — the nightly DAG, run records, acute routing, alerts, missed cases
  db/          Encrypted storage. AES-256-GCM at rest, key custody, retention.
               FAILS CLOSED — there is no plaintext path. Read keys.py first.
  api/         L6 — FastAPI, 21+ routes, voice routes and /api-console attached separately
web/           Next.js 15 App Router console — four operational dashboards + installable manifest
tools/         portability_check · package · benchmark · train_tabular ·
               render_artifacts · check_locales
docs/          PS_COMPLIANCE · TECH_STACK · CONTEXT_PHASES · SCALABILITY ·
               PHASES · RECONCILIATION · artifacts/ (5 PDFs + their HTML sources)
```

Read `core/gates.py` first. It is short and it is the entire argument.

Then, in order:

1. `docs/CONTEXT_PHASES.md` — every phase, what is done, what is **Open**, and
   the evidence for each claim. Its "Open" table is the next-procedure list.
2. `docs/TECH_STACK.md` — the declared stack against what actually runs and
   where, what happens when each part fails, and the tech-stack questions a
   judge will ask.
3. `docs/PS_COMPLIANCE.md` — the problem statement line by line, with the gaps
   named rather than buried.

## The scalability answer, since it will be asked

Measured, reproducible with `uv run python tools/benchmark.py --write`, written
to `docs/SCALABILITY.md`. **7.7 ms per person** at the largest cohort measured
(4,000 people, 7.6 million records), and *sub-linear* across a 16.7× range —
per-person cost falls as the cohort grows, because the fixed startup cost is
amortised. Ten lakh personnel is about **2.1 hours on one core, 16 minutes on
eight**. One commodity server, well inside an overnight window, no GPU and no
distributed system.

Do not quote an older figure of 35 ms per person if you find one. It predates
the fix of four quadratic lookups in the store and the bootstrap, and it is
wrong by roughly 4.5×.

**Say the second half too.** The escalation rate is stable at about 0.8%, which
at ten lakh is roughly 8,200 cases a night — about 1,370 welfare officers at six
conversations each. That is not a deployable number. The constraint is human
capacity, not compute, and the evidence threshold is the dial that sizes it
(0.65 → ~1.20%, 0.70 → ~0.65%, 0.80 → ~0.05%). Presenting the compute number
without the caseload number is the kind of overclaim this project is built to
avoid.

## Honest limitations. State these; do not paper over them

- **There is no real dataset.** The cohort is generated from seed 26186 at
  training time. The training label is `strain >= 0.55`, which is circular — the
  model learns the generator. The model card is stamped `synthetic: true`. Any
  accuracy figure from this data measures the generator, not the world.
- **Voice cannot detect a person who is fine on the surface and not underneath.**
  Cue-anchored concordance catches "I'm fine" said in a strained voice.
  `sustained_strain()` catches somebody in difficulty who never says it.
  `baseline_shift()` catches drift against the person's own prior sittings.
  Somebody who says it *and sounds fine* is not detectable by voice, and this
  limit is written down as a test rather than hidden.
- **Voice is an add-on, outside the submitted scope.** It is a further way of
  understanding, not a gate input in the base system.

## How to work in this repository

- `./check.sh` before and after any change. It is lint, the full suite, L3
  purity, portability and packaging. It is the definition of "not broken".
- Add a test with any behaviour change. The suite is large (~729 tests) because
  every bug above became one.
- Never add a dependency without checking it has no native build step and no
  download at import time. `tools/portability_check.py` will catch some of this;
  it will not catch all of it.
- Keep comments explaining *why*, not *what*. The existing comments record the
  reasoning behind decisions that look arbitrary, which is the only thing that
  makes them safe to change later.

## What to do first

1. `uv sync --all-extras && (cd web && npm install)`
2. `./check.sh` — confirm green before changing anything. On a fresh copy
   **12 skipped tests are expected**: they need the trained model files,
   which are excluded from the archive because they are rebuildable and
   the pipeline runs without them.
3. `./run.sh` and open the control room at `/demo`.
4. Read `docs/CONTEXT_PHASES.md` for what is open.
