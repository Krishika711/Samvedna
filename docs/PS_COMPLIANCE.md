# PS 26186 — requirement-by-requirement audit

Every line of the problem statement, against what is actually in this tree.
Each row names the file or command that backs it, so any claim here can be
checked rather than taken.

Verified by `./check.sh` on 2026-09-08: ruff clean · **729 tests passed** ·
portability clean across 170 files · 8 locales complete · offline REPLAY run
green · archive 2.31 MB.

Legend: **MET** · **MET, with a stated limit** · **PARTIAL** · **NOT MET**

---

## Description — "the system should…"

| # | Requirement | State | Where |
|--:|---|---|---|
| 1 | Analyse leave patterns, deployment history, duty schedules, transfer frequency, training commitments, workload trends | **MET** | All six are first-class domains in `config/weights.py`: `leave`, `deployment`, `duty_roster`, `transfer`, `training`, `workload` — plus `self_report` (T1) and `biometric` (T3). Nothing in the PS list is missing and nothing is bolted on. |
| 2 | Optional self-reporting and wellness assessments through a **secure mobile application** | **MET** | `/me` in eight languages, installable via `web/app/manifest.ts` (`display: standalone`, deep-linking to `/me`). Real PHQ-9 items and scoring in `components/SelfAssessment.tsx`. A web app rather than a store app, so the force hosts and controls it end to end — the reasoning is in the manifest's own comment. |
| 3 | Voluntary biometric and wellness data, where authorised and legally permissible | **MET** | `biometric` is a separate consent scope, **off by default**, tiered T3. Withheld from command at any group size. |
| 4 | Detect behavioural patterns associated with elevated stress risk | **MET** | Deviation against the person's own 180-day baseline *and* the unit cohort over the same window (`analytics/features/deviation.py`); roster-rhythm features separate *predictable* from *sustainable*. |
| 5 | Generate risk assessments and welfare recommendations for authorised welfare officers **and commanders** | **MET** | Officers get named cases with a recommendation; commanders get aggregate bands plus the levers they control. Two different products for two different jobs, by design. |
| 6 | Enable proactive counselling, welfare interventions, workload balancing | **MET** | Six intervention codes in `core/interventions.py`: `WLF-COUNSEL`, `WLF-LEAVE`, `WLF-REST`, `WLF-PEER`, `WLF-FAMILY`, `WLF-TRAINING`. Workload balancing is the commander's path — rotation, leave backlog, day-14 relief. |
| 7 | Strong privacy safeguards; **welfare support rather than disciplinary action** | **MET** | HMAC pseudonymisation with rotating salt epochs, consent filter *after* pseudonymisation, k-anonymity, differential privacy with a release cache. Outputs are barred in software from ACR, posting, promotion and disciplinary processes. |

---

## Expected Solution — the eight components

| # | Component | State | Where |
|--:|---|---|---|
| 1 | Personnel Wellness Monitoring Dashboard | **MET** | `/officer` (caseload) and `/unit` (aggregate strain). |
| 2 | Mobile-based Wellness and Self-Assessment Application | **MET** | `/me`, installable, eight languages. |
| 3 | Predictive Behavioural Analytics Engine | **MET** | `pipeline/dag.py` — nine stages, per-stage timings and row counts. |
| 4 | Stress and Burnout Risk Prediction Models | **MET, with a stated limit** | `GradientBoostingClassifier` + TreeSHAP, plus a discrete-time hazard model for a "by when". **The training data is synthetic and the label is circular** — see Limits below. |
| 5 | Welfare Intervention Recommendation System | **MET** | `core/interventions.py`, with the actionability gate as a hard veto on an intervention that does not fit, is already running, or was not consented to. |
| 6 | Role-based Access Control and Privacy Management Framework | **MET** | `disclosure/rbac.py` — five roles, purpose binding, unit scoping. `disclosure/` is the only layer that can re-identify. |
| 7 | Automated Alerts for authorised welfare personnel | **MET** | `pipeline/alerts.py` — `AlertQueue` with live and **shadow** dispatch modes, so a phase-1 deployment issues no alerts at all while still producing the record. |
| 8 | Data anonymisation and secure storage mechanisms | **MET** | Anonymisation: `ingest/pseudonymise.py`, `ingest/dp.py`, `disclosure/kanon.py`, `disclosure/dpcache.py`. **Secure storage: `db/store.py` + `db/crypto.py` + `db/keys.py`** — AES-256-GCM at rest, pid-bound, fail-closed key custody. Append-only hash-chained ledger in `disclosure/audit.py`. |

---

## Preliminary Scope

| # | Item | State | Where |
|--:|---|---|---|
| 1 | Predictive behavioural analytics algorithms | **MET** | Deviation, tabular risk, survival horizon, roster rhythm, three-reviewer panel. |
| 2 | Mobile-based wellness self-reporting platform | **MET** | As above. |
| 3 | AI-driven stress and burnout risk assessment engine | **MET, with a stated limit** | Synthetic training data. |
| 4 | Commander and Welfare Officer dashboard | **MET** | Two separate surfaces, deliberately not one with a permission flag. |
| 5 | Automated intervention recommendation system | **MET** | `core/interventions.py`. |
| 6 | **Secure integration with HRMS and personnel management systems** | **MET** | `ingest/ports.py` defines the `Connector` protocol; `ingest/connectors/hrms.py` is the reference implementation, reading a nightly HRMS export from a file share. **No outbound connection, no credential in the analytics tier, no live dependency that can fail a welfare run.** A pull-from-API connector satisfies the same protocol and would be the less secure of the two. Nine tests in `tests/pipeline/test_hrms_connector.py`. |
| 7 | Privacy-preserving analytics and role-based access controls | **MET** | As above. |

---

## Key Technical Challenges — the six hard ones

### 1. Privacy and confidentiality of sensitive personnel data — **MET**

The service number exists for exactly one hop, connector to `normalise`, and
nothing downstream accepts the type that carries it. The consent registry is
keyed by pid, so even the consent store holds no identifier. Withdrawal is
readable through exactly one function named `revocations_for_auditor` — no
count, no rate, no per-unit view exists for a dashboard to group by.

### 2. Preventing stigmatisation — **MET**

This is what the four gates are for. On the reference run, 240 people screened,
128 deviating, **3 named**. The other 125 were watched and not named. A
commander sees no individual at any group size, and the self-report, biometric
and voice domains are withheld from command entirely. The refused list is
auditor-only and returns 403 to a welfare officer, because an officer handed a
nearly-flagged queue would work it.

### 3. Minimising false positives **and false negatives** — **MET, with a stated limit**

Both halves are now measured, and the second half was a genuine gap found while
auditing against this brief.

* **False positives**: realised precision from closed cases
  (`pipeline/calibration.py`), on the officer's own header. Below a 0.70 floor
  the system proposes *tightening*.
* **False negatives**: `pipeline/missed.py`. When a welfare concern surfaces
  through another channel — self-referral, commander referral, medical,
  incident, peer concern — it is registered with what SAMVEDNA's verdict for
  that person was at the time, and which gate declined them. Above a 0.30
  missed-case ceiling the system proposes *loosening* the gate that blocked a
  majority of the recoverable misses.

Three guard rails, all tested in `tests/pipeline/test_missed.py`:

* A quiet week alone never loosens. Absence of complaint is not evidence.
* Both errors high at once never loosens — that means the model is wrong, and
  moving a threshold trades one harm for the other.
* No proposal is ever applied by the thing that generated it. A governance
  board approves, and the decision is minuted.

**The limit, stated plainly:** this is *surfaced-case recall*, not recall. The
denominator counts only concerns that came to light some other way, which is
biased toward concerns severe enough to surface. A concern nobody ever raised is
invisible to the figure. True recall needs a gold standard for the whole cohort
and is not obtainable outside a research protocol. The constant is called
`LIMITATION` and it says this in words that survive being pasted into a slide.

**Before this module existed, `propose()` could only ever raise a threshold** —
so given enough quiet weeks it converged on naming nobody, which is
indistinguishable from having no system.

### 4. Ethical and transparent AI decision-making — **MET**

* No model, LLM or heuristic may emit a gate value, a verdict or a confidence.
  Models produce features and a score; arithmetic in `core/gates.py` decides.
* `core/` is pure — an AST test parses every module and fails the build on I/O,
  a clock, `random`, `numpy`, or any `samvedna.*` import outside `core` and
  `config`.
* Every gate shows its formula with the real numbers in it.
* Mind-change text is computed by inverting the failed gate, never generated,
  so it cannot describe a route that would not in fact clear the gate.
* Domain tiers are config, never model-assigned.

### 5. Securing sensitive psychological information against cyber threats — **MET, with a stated limit**

**Encryption at rest** — `db/crypto.py` and `db/store.py`. AES-256-GCM, one
sealed blob per identity, **bound to its pid as additional authenticated
data**. The AAD is the part worth explaining: without it, an attacker with
write access swaps one person's ciphertext onto another person's row and the
system discloses the wrong name — an attack that needs no key at all. The
claim is tested by grepping the raw database files for the plaintext.

**Key custody** — `db/keys.py`. `HsmKeyProvider` is the production path and it
**refuses rather than faking it**; a stub returning a locally-derived key while
calling itself an HSM provider would be the most dangerous class in the
codebase. `KeyfileProvider` demands mode 0600 and a path *outside the project
tree*, and refuses both otherwise — an in-tree key would be committed and then
emailed inside the archive. `PassphraseProvider` (scrypt) is marked
`is_production_safe = False`, and live mode refuses it, checked in two places.

**Erasure** — three steps, each because the previous was not enough:
`PRAGMA secure_delete` zeroes the row rather than freeing the page, `VACUUM`
rewrites the file without freed pages, and `wal_checkpoint(TRUNCATE)` clears
the write-ahead log, which still held the frames after the first two. Found by
grepping a purged pid out of the raw files. Under the DPDP Act erasure has to
mean erasure.

**Fail closed everywhere.** There is no configuration in which this system
writes an identity in the clear. A missing key, an unsafe provider, an
unreadable ciphertext or a stale salt epoch all refuse.

**Also done:** no outbound network calls at all (enforced —
`tools/portability_check.py` fails the build on an external endpoint); no
credentials in the tree; no third-party analytics SDK; no public LLM API; the
HRMS seam reads a file rather than holding a credential; an append-only
hash-chained ledger where a failed write aborts the disclosure; role and
purpose binding in one layer rather than in the interface.

**The limit:** network segmentation, OS hardening, key *rotation*, and a
penetration test are deployment activities, not code. And no amount of
application-level crypto substitutes for volume encryption on the host — what
is claimed here is that the one table holding PII is protected independently of
the filesystem, not that the deployment is hardened.

20 tests in `tests/storage/test_secure_store.py`.

### 6. Building trust among personnel — **MET**

The transparency screen is not a link, it is the page, and every word of it is
translated — a transparency screen somebody cannot read is not transparency. A
missing translation key is a build failure, never an English fallback. Consent
is recorded against a specific text in a specific language at a specific
version, and an unreviewed translation cannot ground consent: saving is refused
rather than accepted quietly. Withdrawal is one tap and is never reported to
anybody.

---

## Expected Benefits — which are demonstrable now

| # | Benefit | Demonstrable? |
|--:|---|---|
| 1 | Early identification of personnel needing welfare support | **Yes** — the survival horizon gives a "by when", which is what makes a case schedulable rather than just scored. |
| 2 | Reduction in stress-related incidents | **Not yet** — needs a field trial. `pipeline/missed.py` is the instrument that would measure it. |
| 3 | Improved mental well-being and resilience | **Not yet** — needs a field trial. |
| 4 | Enhanced readiness and operational effectiveness | **Not yet** — needs a field trial. |
| 5 | Better workload distribution | **Yes, mechanically** — the op-tempo confounder reframes a unit-wide pattern as a command workload problem instead of naming individuals. That reframing *is* the workload finding. |
| 6 | Improved retention and job satisfaction | **Not yet** — needs longitudinal data. |
| 7 | Data-driven welfare planning and resource allocation | **Yes** — the escalation-rate curve against the evidence threshold (1.20% / 0.65% / 0.05%) is exactly a resource-allocation instrument, with the staffing arithmetic attached. See `docs/SCALABILITY.md`. |
| 8 | Reduction in incidents from prolonged occupational stress | **Not yet** — needs a field trial. |

Four of eight are demonstrable from the running system. The other four are
outcome claims that no amount of engineering can evidence without a deployment,
and this document is not going to assert them.

---

## Strategic Importance

| Claim | State |
|---|---|
| Enhances force readiness and personnel welfare | Mechanism present; outcome needs a trial. |
| Supports evidence-based welfare management | **MET** — every verdict carries its arithmetic, and every refusal carries what would change it. |
| Strengthens organisational resilience | Mechanism present; outcome needs a trial. |
| Promotes preventive rather than reactive care | **MET** — the survival horizon and the persistence gate are both forward-looking; the acute override handles the reactive case without waiting for a window. |
| **Indigenous capability tailored to Indian CAPFs and Armed Forces** | **MET** — eight Indian languages with script-aware typography; rank and unit structures throughout; no dependency on any foreign cloud, API or model; runs air-gapped on hardware the force already owns. |

---

## Limits, stated rather than buried

1. **There is no real dataset.** The cohort is generated from seed 26186 at
   training time and the label is `strain >= 0.55`, which is circular — the
   model learns the generator. The model card is stamped `synthetic: true`. Any
   accuracy figure from this data measures the generator, not the world.
2. **False-negative measurement is surfaced-case recall, not recall.** See
   challenge 3.
3. **Cyber-security is application-level.** Encryption at rest, key custody and erasure are built and tested. Network segmentation, OS hardening, key rotation and a penetration test are deployment activities. See challenge 5.
4. **PHQ-9 translations are not licensed.** The instrument is implemented with
   real items and real scoring, and the locale files refuse to serve a
   translation that has not been supplied by the licence holder.
5. **Compute scales; the caseload does not.** 7.7 ms per person, sub-linear
   across a 16.7× range, ten lakh in 2.1 hours on one core. But the escalation
   rate is stable near 0.8%, which at ten lakh is ~8,200 cases a night and
   ~1,370 officers. That is an operating-point decision and the dial is
   exposed, not a compute problem — and quoting the first figure without the
   second would be exactly the overclaim the gates exist to prevent.
6. **Voice is an add-on, outside the submitted scope**, and it cannot detect
   somebody who says "I'm fine" *and sounds fine*. That limit is written down
   as a test.

---

## How to check any of this

```bash
./check.sh                                     # lint · 729 tests · purity · portability · packaging
uv run samvedna cohorts                        # the three fixture cohorts through the real gates
uv run samvedna case pid-mon-0001              # the refused case, arithmetic shown
uv run python tools/benchmark.py --write       # regenerate docs/SCALABILITY.md
uv run pytest tests/pipeline/test_missed.py -v # the false-negative half
uv run pytest tests/pipeline/test_hrms_connector.py -v  # the HRMS seam
uv run pytest tests/storage -v                 # encryption at rest, and every refusal
./run.sh                                       # then open /demo
```
