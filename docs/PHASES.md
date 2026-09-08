# SAMVEDNA — build and validation phases

Head-to-toe checklist against PART 12 of the master prompt. Every box is either
done and **evidenced** — a command was run and its output checked — or open with
a reason. "It looks right" is not evidence.

Legend: `[x]` done & verified · `[~]` partial, reason given · `[ ]` open

Close a phase by running `./check.sh` and pasting what it printed.

---

## Phase 0 — Contracts and configuration

Ship gate: *compiles, no stray literals.*

- [x] `core/types.py` written first: 18 frozen dataclasses, each stage's output
      the next stage's input
- [x] `RiskAssessment` has no `verdict` and no `confidence` field — PART 14
      forbids a model emitting either, and the cheapest enforcement is leaving
      nowhere to put it
- [x] `config/` holds every number a verdict depends on: `weights.py`
      `thresholds.py` `windows.py` `flags.py`
- [x] `CONFIG_VERSION` stamped on every verdict, so a prior verdict stays
      reproducible against the configuration it was made under (PART 8.9)
- [x] **Stray-literal check is mechanical, not a review item**
      (`tests/core/test_config_discipline.py`). It found two on first run:
      `gates.py` rebuilt the persistence window/weight mapping locally, and
      `mindchange.py` had a bare `30` for the primary window. Both now come from
      `config/windows.py`. A threshold that drifts into `gates.py` is not a style
      problem — it is a number no governance board approved, sitting in the path
      that decides whether a jawan is named
- [x] **L3 purity is asserted, not asserted-to**: a test parses every module in
      `core/` and fails on an import of sqlalchemy, httpx, torch, numpy, asyncio,
      `time`, `random`, `os` or `logging`, and on any import from a `samvedna.*`
      package other than `core` and `config`

## Phase 1 — Gates, verdict, mind-change, confounders

Ship gate: *all three fixture cohorts produce intended verdicts.*

- [x] `gates.py` — four pure functions, each returning every input term it was
      computed from plus a formula string with the numbers substituted
- [x] `confounders.py` — five deterministic rules; masses sum rather than max, so
      "adding a confounder never raises consistency" holds as a property
- [x] `verdict.py` — precedence exact, irrecoverable conditions before
      recoverable ones
- [x] `mindchange.py` — every item computed by inverting a gate; no free text
- [x] `interventions.py` — playbook matching on driver keys, never on prose
- [x] `machine.py` — illegal transitions raise; nothing reaches `ESCALATED`
      except from `GATED` or an officer's manual escalation of a `MONITORED` case
- [x] **All five evidence rows of PART 6.65 reproduce exactly**: 1.000 / 0.800 /
      0.675 / 0.246 / 0.183
- [x] **The demo row reproduces exactly.** Three sustained, corroborating
      domains against a unit where 45–61% of the cohort deviates the same way:
      consistency **0.694** against a **0.700** threshold, verdict MONITOR, no
      name produced, and the mind-change item names the op-tempo confounder and
      its 0.70 mass
- [~] **PART 6.65 row 8 prints 0.467; this build computes 0.000.** The published
      figure is `w/(w+0.8)` — the domain's own weight in the numerator, i.e. a
      domain corroborating itself. Under that rule the demo row above computes to
      **0.774 and passes** the 0.700 threshold, which would destroy the single
      most defensible moment in the design. Excluding self reproduces the demo row
      exactly (25/36 = 0.69444) and scores a lone confounded domain 0, which is
      the honest answer: one domain has no corroboration at all. Same *outcome*
      as the published row (fail); different displayed value. Documented in
      `gates.consistency` and in `tests/core/test_consistency.py`
- [x] Persistence rows reproduce: 0.965, 0.720, and **0.332 from the natural
      inputs for one bad week (7/7, 7/30, 7/90) with no tuning**
- [x] Actionability rows reproduce: 1.000 / 0.750 / 0.000 / 0.000, and
      `test_a_weighted_sum_would_leak` pins the PART 6.5 argument as a test — a
      weighted sum scores **0.85 for a person who never consented to contact**
- [x] Safety override: instrument-triggered, bypasses persistence and evidence,
      routes to `MH-URGENT` (mental-health authority, never the unit), records
      the gates it bypassed. A model score of 0.999 does **not** trigger it
- [x] 11 property invariants (Hypothesis, 200 examples each), including "the
      composite never affects the decision" and "no ESCALATE without consent
      covering a deviating domain"
- [x] **Three fixture cohorts pass through the real gate engine.** The REPLAY
      loader drops the fixture's own `expected` field, so constraint 8 — the
      MONITOR path is produced by the gates, never by a demo branch — is
      structurally true rather than promised
- [x] Fixtures reproduce byte-for-byte from a fixed seed
- [x] **Three fixture expectations were wrong and the engine was right.** One
      confounder per domain does not defeat three corroborating domains (needed
      two stacked benign explanations); a lone opt-in biometric trend matches no
      welfare action, so actionability vetoes and the cycle correctly closes as
      NO_FLAG; and partial consent to service records alone **still escalates on
      breadth**, which is a better story than the fixture originally claimed

**Evidence — `./check.sh`:** ruff clean · **106 tests passed** · portability clean
across 35 files · fixtures deterministic · archive 0.06 MB, within the attachment
limit.

## Transfer discipline (standing, checked every phase)

The tree has to survive being copied to a pendrive or sent as an email
attachment, so it is checked rather than remembered.

- [x] `tools/portability_check.py` — fails on absolute home paths, email
      addresses, company names, hosted-vendor references, hardcoded credentials
      and external LLM endpoints. Runs in `check.sh`
- [x] `tools/package.py` — refuses to build if portability fails, excludes every
      rebuildable directory, rejects file types mail gateways block, and fails if
      the archive exceeds the attachment limit

## Phase 2 — Synthetic cohort generator

Ship gate: *realistic roster/leave/deployment sequences.*

- [x] `ingest/generator.py` — a synthetic force of units, personnel and daily
      service records, deterministic under a seed
- [x] **Sequences have structure, not white noise.** Duty and workload move in
      blocks because rosters are planned in blocks; deployments are contiguous
      tours; transfers are step functions; a self-assessment is a sparse event
      with the value carried forward, not a stream. This is asserted
      (`mean run > 3 days`, `mean tour > 14 days`), because a persistence gate
      scored against independent daily noise looks far better than it deserves —
      the 7/30/90-day windows all see the same noise and agree with each other
- [x] **One unit is under operational surge**, lifting every operational domain
      for everybody in it on the same days. That is the pattern the op-tempo
      confounder exists to catch, and it now arises from the generator rather
      than from a fixture asserting it
- [x] Strain is Beta(2, 6) — a long right tail, so the positive class stays rare
      and the problem stays real (median strain < 0.35, asserted)
- [x] Strain is only weakly legible from any single domain, deliberately. If it
      were legible from one, none of the four gates would be needed
- [x] Roughly a third decline the self-assessment channel and over half decline
      biometrics, so the consent filter has something real to do
- [x] Synthetic service numbers are obviously synthetic (`UNIT-nn-nnnnnn`)

**Evidence:** 15 generator tests · 120 personnel × 270 days = 228,584 records in
0.46 s.

## Phase 3 — Ingest, pseudonymisation, consent filter

Ship gate: *no identifier past L1, proven by test.*

- [x] `pseudonymise.py` — HMAC-SHA256 under a rotating salt, 128-bit pid.
      Deterministic within a salt epoch, one-way outside it. Not a bare digest:
      an unsalted hash of a six-digit service number is a rainbow table
- [x] Salt epochs are contiguous and non-overlapping; rotating changes every pid,
      which caps how far back a compromised salt can re-identify
- [x] The salt never appears in `repr`, in a record, or in an exception message
- [x] `ingest/ports.py` — `Connector` and `ConsentRegistry` protocols, so a
      REPLAY connector and a live records connector are indistinguishable
      downstream. That is what makes constraint 7 architectural rather than a mode
- [x] Seven REPLAY connectors, one per domain, each with injectable failure and
      partial-return behaviour so degradation can be *demonstrated*
- [x] `normalise.py` — pseudonymise **then** consent-filter, in that order, so
      the consent registry itself holds no identifier
- [x] Unconsented domains are **discarded, not marked**. A record that exists
      downstream is a record something can accidentally use
- [x] `disclosure/consent.py` — four-state lifecycle (Workflow B); the
      welfare-contact toggle is independent of analysis scope
- [x] **Revocation has exactly one accessor and its name says who may call it.**
      No count, no rate, no per-unit view exists for a dashboard to group by —
      PART 14 forbids surfacing that a person revoked, and the enforcement is
      that there is nothing to read
- [x] `ingest/dp.py` — Laplace noise on aggregates with a **budget that runs
      out**. An exhausted budget raises rather than serving one more, and the
      caller cannot reset it: a dashboard refreshable without limit has no
      privacy guarantee. Noise is centred on the truth, scales inversely with
      epsilon, and is scaled harder for small cohorts
- [x] A failed connector excludes its domain and reports `missing_fraction`;
      nothing is ever imputed or smoothed over

**Evidence — `./check.sh`:** ruff clean · **152 tests passed** · portability clean
across 50 files · archive 0.09 MB.

## Phase 4 — Feature store and deviation detection

Ship gate: *deviations match hand-computed fixtures.*

- [x] `features/store.py` — rolling per-pid, per-domain series; personal and unit
      baselines; ages out on schedule
- [x] **The baseline is disjoint from every window being scored** (`BASELINE_LAG_DAYS`).
      Found by measurement, not by review: a trailing 180-day mean *contains* a
      60-day surge, so the deviation lifts the very baseline it is measured
      against. On the synthetic force an obvious unit-wide surge produced
      **z_self = 0.83 against a 2.0 threshold — invisible**. Lagging the baseline
      by the longest scored window (90 days) fixed it; op-tempo cohort fractions
      went from 12% to 48–68%
- [x] Same-day rows collapse to their mean, so ingest order cannot change a feature
- [x] A never-moving series cannot produce an infinite z (`MIN_STDEV` floor)
- [x] **Breach fraction is over elapsed days, not over rows present.** Three
      observations in ninety days must not report a breach fraction of 1.0 —
      persistence would read as sustained when almost nothing was recorded
- [x] The unit baseline is built from per-person window means, not pooled rows: a
      hundred people with one high day each is a different thing from one person
      with a hundred high days, and pooling cannot tell them apart
- [x] Too little personal history produces **no deviation** rather than falling
      back to a peer comparison. "Different from your peers" is not the same
      claim as "different from yourself", and only the second is about welfare
- [x] Tier and weight are read from config in the detector too — nothing in the
      analytics layer can promote a domain
- [x] Opposite directions do not add up into a false op-tempo reading
- [x] Generator: per-person `surge_exposure`, because a uniform lift made 92% of
      a unit deviate. A surge is not uniform — a quick-reaction sub-unit is on the
      line while the quartermaster's staff are not

### The consistency gate had a real statistical flaw, and the funnel exposed it

Running the whole force through the real gate engine produced **five escalations
inside the surged unit and one outside it** — exactly backwards. The cause was in
`gates.consistency`, not in the data:

> A jawan deviating in `deployment`, `duty_roster`, `leave` and `workload`, where
> the surge explains the last three. The published formula scored `deployment` at
> `2.10/(2.10 + 0) = **1.000**` — full marks for being corroborated by three
> domains that agree with each other *only because they share a cause*. That is
> the ecological fallacy with a threshold attached, and it is the same error the
> evidence gate's breadth requirement exists to prevent.

Fixed by discounting a supporting domain's contribution by its own **unshared**
confounder mass, and dividing by the support that was theoretically available so
an uncontradicted domain cannot still score 1.000 on discounted evidence.

- [x] **Every published calibration row is preserved exactly.** When all domains
      share the same confounder nothing is unshared, so PART 6.65 row 7 still
      computes to 25/36 = 0.694. Asserted directly
- [x] The officer can see the discount in the gate panel, not just its effect:
      the per-domain term reads `0.84/(1.40+0.00)`
- [x] Funnel after the fix: **120 screened · 69 deviating · 1 escalated**, and
      the surged unit produces **zero** escalations — the op-tempo confounder
      reframes it as a command workload problem, which is the entire thesis

**Evidence — `./check.sh`:** ruff clean · **169 tests passed** · portability clean.

## Phase 5 — Tabular risk model and SHAP attribution

Ship gate: *calibrated, subgroup metrics reported.*

- [x] **The claim the whole design rests on is a test.** A model score of
      **1.000 moves no gate value and no verdict**, and a score of 0.000 cannot
      veto an otherwise sound case. `RiskAssessment` has no field named
      `verdict`, `decision`, `confidence`, `escalate` or `flag` — asserted, so
      there is nowhere to smuggle one in
- [x] **Backend is scikit-learn, and that is a portability decision.** The first
      training run died with `Library not loaded: @rpath/libomp.dylib` —
      LightGBM's wheels link against OpenMP, which on macOS is a Homebrew install
      and simply absent on a clean machine. A system that has to survive being
      copied to a pendrive or emailed cannot carry a native dependency the
      recipient must go and install. Gradient boosting from scikit-learn is the
      same algorithm family, ships self-contained, and is fully supported by
      SHAP's TreeExplainer. LightGBM remains an optional `fast` extra
- [x] **The threshold is selected for precision, not F1** (0.75, precision
      0.938, recall 0.789). F1 treats a missed case and a wrongly-named soldier
      as equally bad; in this system they are not
- [x] Isotonic calibration; expected calibration error **0.013**, so a score of
      0.7 means roughly what it says. An uncalibrated score is not a probability
      and every downstream use of one is wrong
- [x] AUROC **0.9195** on held-out synthetic data — and the model card is stamped
      `synthetic: true`, because PART 9 forbids reporting it as validation
- [x] Rare positive class (3.2%) handled by class weighting rather than
      resampling, so the model still sees the true prevalence
- [x] **Subgroup performance published across all four axes PART 9 names** —
      rank, age band, unit type, deployment category. Widest *measurable* AUROC
      gap **0.250**
- [x] **A subgroup with fewer than 3 positives is reported as NOT MEASURED, not
      scored.** The first version printed `AUROC 0.500` for a subgroup with one
      positive, which reads as "no skill" when it means "no evidence". A fairness
      table that conflates them is worse than one that says nothing: the first
      invites a conclusion, the second invites more data. Four subgroups are
      currently unmeasured and are named in the output
- [x] **A tampered estimator refuses to load.** Loading means unpickling, and an
      unverified pickle in a nightly batch is a remote-code-execution primitive.
      The card carries a SHA-256 written at train time and verified at load time
- [x] Isotonic calibrator persists as two float arrays in JSON — no pickle on
      that path at all
- [x] Degrades rather than failing: a missing model returns `None`, an
      unavailable assessment is **labelled** rather than faked, and the pipeline
      still reaches ESCALATE. A system that stops naming people when the model is
      missing is behaving correctly; one that stops running is not

**Evidence:** `tools/train_tabular.py --units 12 --strength 140` → 1,680
personnel, 54 positive · AUROC 0.9195 · ECE 0.0128 · 16 model tests pass.

## Phase 6 — Three reviewers, in parallel

Ship gate: *verdict changes when a confounder appears.*

- [x] `risk_advocate` — deliberately one-sided, so the Confounder Check has
      something real to argue against and the officer sees both. It may only cite
      deviations that exist, with the z-scores they actually have
- [x] `confounder_check` — runs the *same rules* as `core/confounders.py`, so
      what the officer reads and what moved the consistency gate are the same
      facts. The narrative explains the arithmetic rather than competing with it
- [x] `welfare_context` — retrieval over an intervention playbook and
      de-identified precedent cases. **Lexical overlap, not embeddings, and
      deliberately so for v1**: a nearest-neighbour result nobody can check is
      the wrong thing to hand an officer deciding whether to approach a person.
      The seam is a Protocol, so a neural retriever drops in behind it later
- [x] It surfaces an **unsuccessful** precedent as a caution — the most useful
      thing this reviewer can offer is a similar case that turned out not to be a
      welfare issue
- [x] Panel runs all three in parallel (three 0.25 s reviewers complete in
      < 0.6 s, asserted)
- [x] A broken reviewer never fabricates a finding; it returns
      `status: unavailable` with "none has been assumed"
- [x] A missing reviewer is **unavailable, not absent** — the officer still sees
      three panels, one of which says it did not run
- [x] **§8.12 criterion 5 verified:** with Confounder Check forcibly disabled the
      run produces no ESCALATE at all. The gates still run and still pass; only
      the naming is withheld. Losing a *different* reviewer does not freeze —
      only the case against is load-bearing
- [x] No reviewer emits a gate value, a verdict or a confidence (asserted against
      a phrase list), and no module in the package may import `httpx`,
      `requests`, `urllib`, `socket`, `openai` or `anthropic` — asserted by
      parsing the AST, so there is no endpoint to configure one into

## Phase 7 — Safety override (Workflow E)

Ship gate: *acute item escalates same-cycle, bypassing gates.*

- [x] `pipeline/acute.py` — runs on submission, not at 02:00
- [x] **Triggered by the instrument, never by a model.** A risk score of 1.000
      does not fire it; PHQ-9 item 9 endorsed always does
- [x] **Never routes to the commanding officer** — mental-health authority only,
      and the message shown to the person says so in those words
- [x] Bypasses persistence and evidence, **and records the gates it bypassed**,
      so an officer can see afterwards what the arithmetic would have said
- [x] Fires even when consent to welfare contact was withheld: submitting the
      disclosure is itself the consent to act on it
- [x] Severity is not acuity — a high PHQ-9 total with item 9 at zero stays with
      the gates
- [x] GAD-7 and MBI-GS9 have no acute item configured and do not override.
      Inventing one would be a clinical judgement this system has no standing to
      make
- [x] The person is shown **help immediately**, not a submission receipt
- [x] **The SLA clock starts when the person submitted, not when we processed
      it.** The first run of this path produced an acknowledge-by timestamp in
      the past, because a queue delay was silently consuming the window the
      person was waiting inside
- [x] The ledger records **which item fired, never the answers**
- [x] **A failed ledger write shows the person help and dispatches nothing.**
      Withholding help because a database was unavailable would be the worst
      reading of "fail closed"; dispatching without a record would be the second
      worst. The message tells them to contact the authority directly

### The audit ledger (built here because Phase 7 needs it)

- [x] Append-only hash chain; each entry carries the hash of the one before it
- [x] Altering, removing or reordering an entry breaks verification, and
      `verify()` names the first break
- [x] **There is no `update`, `delete`, `remove`, `edit`, `amend` or `purge`
      method** — asserted, because append-only-by-convention is not append-only
- [x] A failed write raises so the caller must abort; it cannot be ignored
- [x] Entries hold pseudonyms and the *fact* of an event, never its content

**Evidence — `./check.sh`:** ruff clean · **229 tests passed** · portability clean
across 70 files.

## Phase 8 — Nightly pipeline, state machine, run records

Ship gate: *full nightly run end to end.*

- [x] `pipeline/dag.py` — PART 7's ten stages, each with its own timing, row
      counts and status, written so an Airflow task is a thin wrapper
- [x] `pipeline/record.py` — run records carry the funnel, every stage, and every
      case verdict with its gate values. **Safe to hand to an auditor whole** —
      asserted that no service number appears anywhere in one
- [x] Every state change goes through `core/machine.py`; an illegal transition
      raises
- [x] **Stage 9 (DISCLOSE) is deliberately not in the DAG.** A batch job has no
      purpose binding and therefore no right to a name
- [x] `samvedna run` — a complete offline nightly cycle with gate bars, formulas,
      the case against, and a MONITOR case with its mind-change items
- [x] Real run: **240 screened · 128 deviating · 3 escalated**, top composite
      0.905 (PART 6.65 publishes 0.904 for its escalate case)
- [x] Every degradation path demonstrated from the command line, not described:
      `--degrade leave` → PARTIAL, 3 → 2 escalations · `--break-reviewer
      confounder_check` → **0 escalations, frozen** · `--drift` → 0 escalations,
      frozen system-wide and logged · `--model-dir /nonexistent` → run completes,
      still escalates
- [x] Asserted: **no degradation ever produces more escalations than a clean run**
- [x] Asserted: **the model never changes who is named.** A missing model does
      move some verdicts from MONITOR to NO_FLAG — SHAP driver names widen what
      the playbook can match — but neither names anybody, and the escalated set
      is identical. That is the precise claim, and it is now the tested one

### Two bugs the first full run found

**The data-gap confounder fired on every domain of every person**, producing a
run with zero escalations. Missingness was inferred from observation density and
compared days observed in a 90-day window against 270 expected days — a units
error. The fix is a design correction rather than a divisor: **missingness now
comes from the connector**, which is the only place that knows how many rows it
expected. Density would have stayed wrong even with the units fixed, because a
self-assessment is an event and a transfer is a step function; density marks both
95% missing forever, turning "this person rarely fills in the form" into "the
records are unreliable".

**An empty `Ledger` was falsy**, because the class defines `__len__`. So
`ledger or Ledger()` silently discarded the caller's ledger and wrote the run to
a throwaway — nine entries appended to an object nobody could see, and no audit
trail for the run. Fixed on the class with `__bool__` returning True and a
comment saying why: an empty ledger is not "no ledger". `Cohort` subclasses
`list` and carries the same trap; it is documented rather than changed, because
an empty cohort really is nothing to process.

## Transfer independence (standing, checked by `./check.sh --transfer`)

- [x] **Zero code dependency on any sibling project** — no imports, no paths, no
      files. Verified by AST parse over `src/`, and now enforced: the portability
      check fails on a sibling-project import, on a relative import escaping the
      package, and on any path reaching outside the tree
- [x] No third-party import that is not declared in `pyproject.toml`
- [x] **`uv.lock` ships.** It was excluded at first as "machine-specific", which
      is exactly backwards. Without it, unpacking the archive on another machine
      re-resolved `shap` and picked an llvmlite from 2021 that will not build on
      a current Python — a failure that only appears at the far end of a
      transfer, which is the worst place to find it
- [x] **Proven, not assumed:** `./check.sh --transfer` packages the tree, unpacks
      it into a scratch directory with no relation to this one, installs cold and
      runs the whole suite there. Latest: **240 passed, 8 skipped**, and
      `samvedna run` produced a full nightly cycle in the copy

**Evidence — `./check.sh`:** ruff clean · **248 tests passed** · portability clean
across 74 files · offline REPLAY run · ledger chain verified · archive 0.30 MB.

## Phase 9 — L5 disclosure: RBAC, k-anonymity, re-identification, audit

Ship gate: *commander view provably individual-free.*

- [x] `rbac.py` — every grant is a **(role, purpose) pair**, not a role. A welfare
      officer and an ACR clerk are both "authenticated staff of the same unit";
      what separates them is why they are asking
- [x] **The purpose firewall is a listed refusal, not an omission.** ACR,
      promotion, posting and disciplinary purposes are enumerated in the code and
      refused for every role, so adding one by accident is a diff somebody has to
      defend. Asserted for all five roles
- [x] **Exactly three (role, purpose) pairs may ever re-identify**, asserted
      against the grants table: welfare officer for contact, mental-health
      authority for acute, and a person about themselves
- [x] An officer is refused outside their unit scope, even for a permitted purpose
- [x] **Authorisation raises rather than returning False.** A caller who forgets
      to check a boolean gets a name; one who forgets to catch an exception gets
      a stack trace. Only one of those failure modes is safe
- [x] `reidentify.py` reads as a sequence of refusals — authorisation, then
      consent, then the verdict, then the ledger, then the directory. That order
      is the design: an unauthorised request must not reveal whether the person
      consented, and a name must not exist in the process before its record
      exists on disk
- [x] **§8.12 criterion 7 verified: a failed ledger write aborts the disclosure.**
      A test with an exploding directory proves the directory is never reached
- [x] Denials are logged too — an auditor needs to see what was *asked*. A failed
      write on the denial path is suppressed, deliberately: failing to record a
      refusal must never turn it into a grant
- [x] `Identity` carries no `phq9`, `responses`, `items`, `score`, `instrument`,
      `clinical`, `diagnosis` or `notes` field. PART 8.0 says a welfare officer
      may never see raw psychometric responses
- [x] **§8.12 criterion 2: a cohort below k is suppressed, never rounded** — and
      a suppressed cell does not leak its true n either, because "n=3" is the
      same disclosure the value would have been
- [x] **The commander payload contains no pid anywhere** (asserted over 30
      cases), and `Cell` has no field that could hold one. There is no
      drill-down to hide because there is nothing to drill into
- [x] An exhausted privacy budget **withholds cells** rather than releasing them
      un-noised, and every release is logged with the epsilon spent
- [x] The unit view tells a commander what they *can* do — rostering, leave
      sanctioning, rotation, welfare capacity. A screen that only says no teaches
      people to route around it

**Evidence — `./check.sh`:** ruff clean · **281 tests passed** · portability clean
across 79 files · ledger chain verified.

## Phase 10 — Welfare officer console

Ship gate: *renders from run records.*

- [x] `api/app.py` — seven routes, every one an authorisation decision. The
      header-based identity is a REPLAY-only shim standing where Keycloak OIDC
      goes, and it **returns 501 outside REPLAY mode**, so it cannot survive
      being pointed at live records
- [x] `api/bootstrap.py` — builds a whole console from a real nightly run, so
      every screen renders from an actual run record rather than a fixture of
      what one might look like
- [x] Caseload is ESCALATE-only, unit-scoped, and **carries no name** — revealing
      an identity is a separate, logged POST
- [x] **The gate panel with the formula behind each bar.** A click rather than a
      hover: hover does not exist on the tablets these are read on, and an
      officer being asked "why me?" needs the arithmetic on the screen, not under
      a cursor
- [x] **The case against is shown before the officer can act**, sorted so
      Confounder Check comes first
- [x] Degradation banners at the top of the caseload, not buried in a status
      page. An officer who does not know a connector failed will read a short
      caseload as good news, which is the one misreading that matters
- [x] Mandatory close-out with the four outcome categories; the console blocks on
      contacted-but-unclosed cases
- [x] Verified against a live server: caseload, case detail, disclosure, unit
      view and audit all serve correctly; a commander reading the caseload gets
      403, and a commander reading another unit gets 403

## Phase 11 — Personnel app (Workflows A and B)

Ship gate: *revocation purges within one cycle.*

- [x] Next.js PWA at `/me`. **The transparency screen is not a link, it is the
      page** — "what the system can and cannot see about me" is the first thing
      on it, in two columns, before any toggle
- [x] Per-domain consent toggles, each independently refusable, each labelled
      with its tier and what it actually reads
- [x] **The welfare-contact toggle is separate and says what turning it off
      means**, in those words: the system will analyse and never surface you
- [x] One-tap withdrawal, with the purge stated concretely and "nobody has been
      told" said plainly
- [x] Help resources on the page itself, reachable without waiting for the system
- [x] Consent lifecycle, purge and revocation semantics tested in
      `tests/privacy/test_consent_lifecycle.py` and end-to-end in
      `test_nightly.py::test_a_revoked_pid_does_not_appear_in_the_next_run`

## Phase 12 — Contest-a-flag and outcome capture (Workflows C, G, I)

Ship gate: *annotation suppresses a driver next run.*

- [x] `pipeline/outcomes.py` — close-out, deferral, contest and calibration
- [x] **§8.12 criterion 3:** a case cannot be closed without an outcome category.
      An unrecognised outcome is **refused, not coerced**, and nothing is logged
- [x] **§8.12 criterion 6:** an accepted confounder annotation suppresses that
      driver, and a test proves it reaches the gates — with `leave` suppressed
      the actionability gate fails and the verdict becomes NO_FLAG
- [x] An annotation expires after its configured window. A benign explanation
      that was true in September is not evidence about March
- [x] Three contest outcomes, all logged: a factual error becomes a correction
      request to the records custodian, a benign explanation becomes an
      annotation, and objecting to analysis narrows consent **with no penalty
      and no `case.dismissed` entry**
- [x] Only the fact of contact and its outcome category are stored — the
      `case.contacted` ledger entry has an empty detail dict, asserted
- [x] **`already_known` counts as neither success nor failure** in realised
      precision. Counting it as a success flatters the model; counting it as a
      failure punishes it for being right about somebody already being helped
- [x] **§8.12 criterion 8:** every officer action appears in the ledger with
      actor, timestamp and reason, in order, chain verified

### The refresh button was an averaging attack

Integration against a live server showed one commander unit view spending
**7 epsilon of a 10 epsilon budget**, and the obvious reading — raise the budget
— is exactly the wrong lesson. If each refresh draws fresh Laplace noise around
the same true value, ten refreshes average to the truth, and a larger budget only
buys the attacker more samples.

- [x] `disclosure/dpcache.py` — a released cell is cached against
      (unit, date, label). The same question gets the same answer for the period
      and is charged epsilon **once**; a different question costs epsilon,
      because a different question is a different disclosure
- [x] Asserted: ten refreshes produce one set of values, repeat views cost zero
      additional epsilon, a different unit does cost epsilon, and the ledger
      records how many cells were served from cache

**Evidence — `./check.sh`:** ruff clean · **325 tests passed** · portability clean
across 104 files · web lint clean · `next build` clean, 6 routes.

## Phase 13 — Sequence and survival models

Ship gate: *horizon predictions in the console.*

- [x] `models/survival.py` — discrete-time hazard over 7/30/60/90-day horizons.
      Chosen over Cox because proportional hazards is not obviously true here (a
      jawan's hazard during a deployment and after it are not a constant multiple
      of one another) and because a discrete model composes intervals in a way an
      officer could check
- [x] **Absence reads as absence.** A missing survival model produces
      `unavailable` and no horizon at all, rather than a default that reads as a
      prediction
- [x] No horizon phrase quotes a percentage as confidence — PART 14 forbids it
- [x] **A horizon never bypasses a gate.** A three-day horizon does not lower a
      threshold or shorten a window; the only path that bypasses gates is the
      acute override, triggered by an instrument
- [x] `models/sequence.py` — roster rhythm as four explicit features rather than
      a Temporal Transformer. **The trade is stated plainly**: a transformer
      would learn interactions these four cannot express; what they buy back is
      that an officer can be told "your longest unbroken run was 23 days" instead
      of "the sequence model scored 0.71". The seam is a Protocol
- [x] Two rosters with the same 90-day mean are told apart (6-on-2-off versus a
      60-day block), which is the whole argument for the model
- [x] **A 61-day unbroken run scored regularity 1.00** in the first version —
      perfectly predictable, and the worst roster in the sample. The formula
      conflated *predictable* with *sustainable*. Sustainability is now a
      separate multiplicative term against `SUSTAINABLE_RUN_DAYS`, and the
      ordering is right: sustainable rotation 0.80, clockwork-but-punishing 0.24,
      unbroken block 0.00
- [x] A window with nobody on duty reports **no rhythm**, not a perfect one

## Phase 14 — Federated training and DP-SGD

Ship gate: *privacy budget reported.*

- [x] `models/federated.py` — FedAvg over parameter vectors, weighted by local
      example count. Depends on neither Flower nor Opacus, because both pull
      torch; the aggregation contract is the one Flower implements, so a Flower
      transport replaces the in-process coordinator without touching the arithmetic
- [x] **`UnitUpdate` carries parameters and a count and nothing else** —
      asserted field-by-field against a forbidden list
- [x] **Clip, then noise, in that order.** Noising first would clip the noise as
      well as the update, shrinking it below what the accounting assumed and
      leaving a campaign reporting an epsilon it never achieved
- [x] Clipping never scales a small update *up*. That would let a unit with
      almost no signal speak as loudly as one with a great deal, while the noise
      calibration stayed correct and the model quietly became wrong
- [x] Noise is centred, so aggregation still converges — noise that is not
      centred is a bias, not privacy
- [x] **The budget runs out and the campaign stops.** It does not continue with
      the noise turned down, and a skipped round changes no parameters
- [x] A round with fewer than three units is refused: that is not federation, it
      is two units sharing a model — and a refused round spends no budget

## Phase 15 — Outcome feedback and calibration

Ship gate: *precision measurable from real outcomes.*

- [x] `pipeline/calibration.py` — `propose` generates, `apply_decision` requires a
      recorded human board decision. **There is deliberately no function that does
      both**, and a test parses the source to prove it
- [x] No proposal from fewer than 20 judged outcomes. A threshold change argued
      from four outcomes is argued from noise
- [x] **A good week never proposes loosening.** The asymmetry is intentional: a
      loop that can relax its own bar every time it has a quiet week will
      eventually relax it into the ground
- [x] A proposal may move a threshold by at most 0.05, carries its evidence, and
      does **not** mutate the live config — a config change is a versioned
      release, and prior verdicts stay reproducible against the version they were
      made under
- [x] A lagging subgroup is reported with a **zero** proposed change: a threshold
      applies to everybody, and a subgroup gap is a model problem
- [x] Drift monitor with PSI. **An empty bin is floored, not skipped** — skipping
      makes PSI *fall* when a distribution collapses into fewer bins, which is
      exactly the drift it exists to catch. A collapsed distribution now scores
      higher than a shifted one (8.28 vs 3.40)
- [x] Drift past threshold freezes escalation system-wide, logs `model.frozen`,
      and MONITOR records continue

## PART 8.12 — the eight acceptance criteria, answered by number

`tests/workflow/test_acceptance_812.py` — one test per criterion, in order, so a
reviewer holding the master prompt can run one command instead of trusting that
the criteria are covered somewhere across 387 tests. **All eight pass.**

## Final state

**`./check.sh` — ruff clean · 387 tests passed · portability clean across 114
files · fixtures deterministic · offline REPLAY run · ledger chain verified · web
lint clean · `next build` clean · archive 0.45 MB, within the attachment limit.**

## Phase 16 — Vernacular consent and transparency (the PART 18 gap)

Ship gate: *a person can read the whole consent screen in their own language, and
what they agreed to is recoverable.*

This was listed as the highest-value open item in `docs/RECONCILIATION.md`, on the
grounds that adoption is what feeds the T1 evidence channel and a voluntary
self-assessment is worth a fifth of the evidence gate on its own.

### Eight languages, complete or not offered

- [x] `web/i18n/locales/` — **en · हिन्दी · বাংলা · मराठी · தமிழ் · తెలుగు ·
      ਪੰਜਾਬੀ · اردو**, 52 keys each, covering the entire personnel surface
- [x] Every language is offered **in its own script**, never as an English
      exonym. Somebody looking for their language scans for the shape of their
      own writing; a list reading "Hindi / Bengali / Tamil" in Latin asks them to
      read English in order to escape it. Asserted, including that the name is
      not ASCII
- [x] **Urdu is RTL**, so the direction path is exercised rather than assumed.
      `dir` follows the language on the document element, and the CSS uses
      logical properties (`border-inline-start`, `padding-inline-start`) so an
      RTL layout is laid out rather than mirrored as an afterthought
- [x] Script-aware typography: Indic and Perso-Arabic faces with system-font
      stacks and taller line heights, and **uppercase/letter-spacing disabled
      outside Latin** — both are Latin typographic devices that range from
      meaningless to unreadable on scripts that have no case and whose letters
      join. No webfont CDN: that would be an external request from a screen that
      must work inside the data centre

### A missing key is a build failure, not an English fallback

The usual i18n behaviour puts an English sentence under a Hindi heading. A person
who reads the Hindi and skips the line they cannot read **has not given informed
consent**, and nothing records that it happened — the screen renders, the button
works, and the gap is invisible to everybody including whoever built it.

- [x] `tools/check_locales.py` fails on a missing key, an extra key, an empty
      string, a list that lost or gained a bullet, a bad `reviewStatus` or
      `direction`, a locale naming itself in English, or a `reviewed` locale that
      names no reviewer. It runs in `check.sh`
- [x] **A stale `textVersion` is a failure.** When the source text changes a
      translation is stale until redone; carrying the old version forward would
      let somebody consent to wording nobody translated
- [x] `lookup()` throws on a miss rather than returning the key or an English
      string — on this screen, failing loudly is the only safe behaviour
- [x] A locale copied and left untranslated passes every structural check, so a
      test compares the actual strings and fails on any that are still English
- [x] Two sentences are asserted present in **every** language: the ACR/posting/
      promotion/disciplinary bar, and "nobody is told" on withdrawal. The ACR
      acronym is deliberately left untranslated, because that is how it appears
      on the document a jawan actually holds

### Consent is to a specific text, in a specific language, at a specific version

DPDP §6 requires consent to be informed, and "informed" is a claim about what the
person actually read. A record saying only *that* somebody agreed cannot answer
the question that matters when it is challenged: **agreed to what, in what words?**

- [x] `disclosure/consent_text.py` — a `ConsentReceipt` carries the locale, the
      text version, and a SHA-256 of the exact strings shown
- [x] **A metadata-only change does not invalidate consent.** The hash covers the
      translated content and excludes `_meta`, so bumping a reviewer's name does
      not invalidate every consent given under text that did not change
- [x] **When the text changes, consent goes stale rather than carrying over.**
      `needs_reconsent` reports it with the reason; a consent recorded before
      receipts existed also reports stale, because it cannot answer "to what?"
- [x] The ledger records the locale, version and hash — **never the prose**.
      Asserted by checking the consent text does not appear in the entry
- [x] Withdrawal removes the receipt too: keeping it would leave a record of what
      a withdrawn person had once agreed to, which is content the purge exists to
      remove
- [x] **The `ConsentState` the gates see carries no language field.** The
      decision layer has no business knowing what language somebody speaks

### An unreviewed translation cannot ground consent

- [x] A `draft` locale is **refused with a 422 naming the reason**, and a refused
      consent enrols nobody. Machine-drafted text is fine for showing a reviewer
      what to check; it is not the legal basis for processing psychological data
- [x] An unknown locale is refused too — the system **will not substitute another
      language**, because a fallback here is the harmful default
- [x] `consent_pilot_mode` is the single escape hatch, off by default. It exists
      because a pilot unit reading a draft is how a draft becomes reviewed, and a
      deployment that leaves it on is misconfigured
- [x] `/api/locales` serves `may_ground_consent` per language, so a UI bug cannot
      offer a draft as a basis for consent
- [x] The person is shown the draft banner rather than having it hidden — they
      are entitled to know the words have not been verified
- [x] `check_locales.py --strict` fails on any draft. That is what a production
      deployment runs

### A validated instrument's translation cannot be invented

- [x] **PHQ-9 and GAD-7 are offered only where an officially validated
      translation exists**, with the validation cited on screen. Substituting our
      own would leave the questionnaire looking entirely normal and scoring
      wrong — a silent failure in the one place a wrong number reaches a person
- [x] Where no validated translation exists the app says so, explains why in the
      person's own language, and offers the languages that do have one

### Honest limits

- [~] **Seven of eight locales are machine-drafted and marked `draft`.** They are
      complete, structurally verified, and use service vocabulary rather than
      corporate — but they have not been read by a native speaker, and the system
      refuses to record consent against them. Native review is a procurement
      task, not an engineering one, and the workflow for it is what shipped here
- [~] Validated instrument translations are cited for English and Hindi only.
      Adding a language means obtaining the licensed translation, not translating
      it
- [~] The operator consoles (officer, commander, audit) remain English. That is
      deliberate rather than unfinished: they are worked by officers, and mixing
      languages across a caseload is its own risk. The language picker appears
      only where it belongs

**Evidence — `./check.sh`:** ruff clean · **481 tests passed** · portability clean
across 129 files · **locales: 8 complete, 52 keys each** · web lint clean ·
`next build` clean.


## Phase 17 — Voice concordance (add-on, beyond the submitted scope)

Not in the SIH submission, which names three input sources. Added afterwards at
the owner's request as a further way of understanding, wired in as a full domain
so it can corroborate and tiered T3 so it can do nothing more.

- [x] `analytics/voice/acoustics.py` — six features through explicit reference
      bands, graded 0..1 rather than thresholded. numpy only: Praat via
      parselmouth is more accurate and is a native dependency the recipient of
      the archive would have to install
- [x] F0 recovered within 0.6% on synthetic tones; silence and white noise
      produce no F0; added noise lowers HNR monotonically
- [x] **No audio is ever stored.** `AcousticFrame` has no field it could live in,
      asserted against a forbidden list
- [x] `minimisation.py` — lexical cue bank with hedges, contrasts and negation
- [x] **Negation scope ends at a clause boundary.** *"I haven't slept but I'll
      manage"* was missed, because `haven't` reached across the `but` and
      cancelled a cue it had nothing to do with — yet that sentence is a textbook
      minimisation and the `but` is what makes it one
- [x] `concordance.py` — fusion with a corroboration floor of two features
- [x] **A barely-moved feature no longer counts as corroboration.** Any non-zero
      divergence used to qualify, so a feature a fifth of the way out of band
      corroborated as loudly as one at the far end
- [x] **The owner found a real hole in the design.** The cue-anchored path is
      blind to somebody in difficulty who never claims to be fine — no phrase to
      anchor to, so nothing is measured about a voice that was strained
      throughout. `sustained_strain()` is the answer, at a materially higher bar:
      four features rather than two, further out, and held across 60% of the
      sitting
- [x] **And a second one.** Somebody who says "I'm fine" *and sounds fine* leaves
      no trace against population bands. `baseline_shift()` compares the sitting
      against **that person's own prior sittings**, which is the only reading with
      any purchase on a practised mask — because a mask is usually a change from
      how somebody used to sound, even when it lands inside normal
- [x] **The limit is written down as a test.** A mask held perfectly and held from
      the first sitting is *not detectable by voice*, all three readings return
      nothing, and they are correct to. The case is carried by the eight domains
      a person cannot perform in a sitting
- [x] A voice becoming warmer than usual is not a welfare signal — counting any
      change would make recovery look like deterioration
- [x] **Duty of care discharged, not deferred.** Capturing speech invites
      unstructured psychological disclosure. Acute phrases route the same working
      day, by literal phrase and never by sentiment: *"this roster is killing
      me"* does not fire, *"I want to die"* does
- [x] Voice is a **session domain, not a connector domain**. There is no
      connector that could fetch a voice overnight, and there must not be one
- [x] One sitting cannot clear the persistence gate; the deviation carries no
      words; the transcript is destroyed on `close()`

**Evidence:** 44 voice tests.

## Phase 18 — Role sessions and the working consoles

The gap that mattered most for a demonstration: every page was reachable from one
navigation with hardcoded roles, so the system's entire thesis — who can see what
— was invisible.

- [x] `lib/session.tsx` — four actors mirroring the server's grant table, with
      the choice persisted per device
- [x] `/signin` — each card states what that actor can and cannot see **before**
      you pick it. A boundary cannot be shown from one side of it
- [x] Role-aware navigation, and `Guard` **explains a refusal rather than hiding
      the page**: your permissions beside theirs, and an offer to switch
- [x] The refusals are real. Verified live: commander→caseload **403**,
      auditor→unit **403**, personnel→audit **403**, officer→heatmap **403**,
      commander→contact **403**
- [x] **Workflow C runs end to end and persists.** contact → the list blocks →
      `"handled"` refused **422** → close as `supported` → realised precision
      recomputed. Both actions land in the ledger with the operator id
- [x] Officer actions wired: contact, defer with a mandatory reason, close-out
      with the four categories, and Workflow G contest
- [x] `/demo` — the PART 16 six-step narrative, signing you into whichever role
      each step needs, and telling you to close on step 3
- [x] **Survival horizon and roster rhythm now reach the officer's screen** —
      computed since Phase 13, served since now. The horizon bar marks an even
      chance, because that is the only threshold on a "by when" that means
      anything. Asserted that neither changes a verdict
- [x] `run.sh` — one command. **Frees a port only when what holds it is ours**
      (it nearly killed another of the owner's apps), and waits until the
      console's *stylesheet* resolves rather than its HTML

### Two failures worth recording, both mine

**A production build wiped a running dev server, twice.** `next build` and
`next dev` share `.next`, so every verification build deleted the assets the
running server was still serving. The page kept returning 200 while its
stylesheet returned 404, and rendered as raw browser defaults — which looks
exactly like a broken design and is not one. I kept checking the page status and
never the stylesheet's. Fixed with `distDir: process.env.NEXT_DIST_DIR`, so
`check.sh` builds somewhere else entirely.

**Then another app took port 3000.** A different Next project of the owner's
claimed it, and my verification showed 404s across every route. Ports are now
overridable and default to 3100, and `free_port` inspects process args before
killing anything.

**Evidence — `./check.sh`:** ruff clean · **561 tests passed** · portability
clean · locales 8 complete · web lint clean · `next build` clean, 9 routes.
