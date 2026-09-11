# Phase-wise context — where the work stands

The single document to read to know what is built, what is open, and what each
claim rests on. `docs/PHASES.md` is the build log with the evidence; this is the
state of play.

**Read `HANDOFF_PROMPT.md` first if you are an agent picking this up.**

Legend: **DONE** verified by a command whose output was checked · **OPEN** not
started, with the reason · **LIMIT** deliberately not doing this

---

## Where the system is, in one paragraph

The full decision pipeline is built, tested and running: nine domains through
seven connectors, pseudonymisation, consent filtering, a feature store with
personal and cohort baselines, deviation detection, a gradient-boosted risk
model with TreeSHAP attribution, a survival horizon, roster-rhythm features,
three parallel reviewers, four deterministic gates, mind-change inversion,
acute-disclosure override, an append-only hash-chained ledger, k-anonymity and
differential privacy with a release cache, federated averaging, and four
operational consoles in eight languages. 729 tests pass. It runs from a copied
folder with no network, no database and no GPU.

What is *not* done is anything that needs data this project does not have: real
cohort validation, a real clinical instrument licence, and a real deployment.

---

## Phases 0–18 — built and verified

Full evidence for each is in [`docs/PHASES.md`](PHASES.md).

| # | Phase | State | The thing worth knowing |
|--:|---|---|---|
| 0 | Contracts and configuration | **DONE** | Every threshold, weight and tier lives in `config/`. A test parses `core/` and fails on any policy number that escaped into it. |
| 1 | Gates, verdict, mind-change, confounders | **DONE** | The product. `core/` is pure — an AST test fails the build on I/O, clock, `random` or `numpy` imports. |
| 2 | Synthetic cohort generator | **DONE** | Seed 26186. One unit is put under a surge so the op-tempo confounder is exercised by generated data, not by a fixture. |
| 3 | Ingest, pseudonymisation, consent filter | **DONE** | HMAC pseudonyms with rotating salt epochs. The consent filter runs *after* pseudonymisation, so the filter never sees a service number. |
| 4 | Feature store and deviation detection | **DONE** | Two baselines — own 180-day and cohort-over-the-same-window — which is what separates an individual concern from a command workload problem. |
| 5 | Tabular risk model and SHAP attribution | **DONE** | sklearn, not LightGBM: `libomp` is a native dependency that breaks the copy. |
| 6 | Three reviewers, in parallel | **DONE** | Confounder check, precedent check, counter-argument. A reviewer being unavailable degrades the run; it does not silently pass. |
| 7 | Safety override (Workflow E) | **DONE** | PHQ-9 item 9 bypasses every gate, routes to a mental-health authority, SLA from submission time. |
| 8 | Nightly pipeline, state machine, run records | **DONE** | Nine stages with per-stage timings and row counts, which is what made the performance work below possible. |
| 9 | L5 disclosure: RBAC, k-anonymity, re-identification, audit | **DONE** | The only layer that can resolve a pid to a person. A failed ledger write aborts the disclosure. |
| 10 | Welfare officer console | **DONE** | Rebuilt as an operational queue — see Phase 19. |
| 11 | Personnel app (Workflows A and B) | **DONE** | Per-domain consent, one-tap withdrawal, and a consent record bound to the exact words in the exact language at the exact version. |
| 12 | Contest-a-flag and outcome capture | **DONE** | Close-out categories only. What was said in a welfare conversation is never stored. |
| 13 | Sequence and survival models | **DONE** | Discrete-time hazard, not a transformer: `torch` cannot be emailed. Roster rhythm separates *predictable* from *sustainable*. |
| 14 | Federated training and DP-SGD | **DONE** | Clip-then-noise ordering, finite epsilon budget. |
| 15 | Outcome feedback and calibration | **DONE** | Realised precision is computed from closed cases and shown on the officer's header. |
| 16 | Vernacular consent and transparency | **DONE** | Eight languages, complete or not offered — a missing key is a build failure, never an English fallback. An unreviewed translation cannot ground consent. |
| 17 | Voice concordance (add-on) | **DONE** | numpy-only DSP. Three readings: concordance gap, sustained strain, baseline shift. |
| 18 | Role sessions and the working consoles | **DONE** | Four actors mirroring the server grant table. A refusal is explained, not hidden. |

---

## Phase 19 — Operational dashboards (this phase)

The consoles existed but read as an explanation of the system rather than the
system. Four numbered cards telling a presenter what to point at is a useful
artefact and the wrong thing to put inside running software.

- **DONE** `/officer` — a queue with filters (to review / awaiting close-out /
  closed), priority column, expand-in-place detail, and a header that says how
  many cases owe a close-out. The counter-argument still renders *above* the
  action buttons; an officer who clicks "contact" and then reads that 61% of the
  unit shows the same pattern has been given an instruction, not decision
  support.
- **DONE** `/unit` — a sub-unit × domain matrix with a one-sentence headline, the
  raised cells listed in order, and the levers a commander actually holds.
  Suppressed cells stay suppressed across refreshes.
- **DONE** `/audit` — tabbed: refusals (nearest-miss first, with the arithmetic
  and the inverted gate), the ledger with a filter, and the privacy budget.
- **DONE** `/me` — operational header with three status tiles; the enrolment
  prose folded into a disclosure rather than opening the page. The helpline card
  stays open, because a person in difficulty should not have to click a triangle
  to reach a number.
- **DONE** `/demo` — was a six-step walkthrough, now the control room: live stage
  timings and funnel counts from `/api/run`, and one door into each console.
  What each role **cannot** see is on the door, because the boundaries are the
  design.
- **DONE** Displaced explanatory content published as artefacts and PDFs rather
  than deleted.

---

## Phase 20 — Performance and scalability (this phase)

Started as a documentation task — the scalability numbers had been quoted from
an in-session measurement and never written down. Writing `tools/benchmark.py`
to make them reproducible found that they were wrong.

**Four quadratic paths, all the same mistake:** a lookup scanning a whole
collection to answer a question a dict could answer.

| Where | What it did | Cost |
|---|---|---|
| `api/bootstrap.py` consent scope | `any(r.pid == ... for r in force.records)` per person per domain | O(people × domains × records) |
| `store.unit_of(pid)` | scanned every `(pid, domain)` key | O(series) per call, once per person |
| `store.domains_for(pid)` | same scan | O(series) per call, once per person |
| `store.unit_baseline(...)` | recomputed the cohort mean once per member of the cohort | O(cohort) per person per domain |

Plus two constant-factor problems in the same stage: `Series.window()` re-sorted
the entire history on all 1.5 million calls, and `statistics.pstdev` computes an
exact sum of squares in `Fraction` arithmetic — 36 of 63 seconds inside
`fractions.py` and `math.gcd`, for a number that is then floored at 0.02 and
compared against a threshold of 2.0.

- **DONE** All six fixed. Per-person cost went from growing (22 ms → 41 ms
  across a 4× cohort range) to falling: **7.7 ms at 4,000 people**,
  sub-linear across a 16.7× range. Ten lakh is 2.1 h on one core.
- **DONE** **Escalation counts are identical before and after.** 3 / 2 / 9 on
  the three cohorts, rates 1.25% / 0.42% / 0.94%. No decision changed.
- **DONE** `tests/pipeline/test_store_performance.py` — six tests pinning cache
  invalidation, out-of-order arrival, index agreement, and float-vs-exact
  standard deviation. Writing them found a seventh bug: `age_out` deleted
  straight out of `points`, leaving the ordered mirror describing rows that no
  longer existed, so aged-out values kept appearing in windows. Retention now
  belongs to `Series.drop_before`, the one method allowed to mutate `points`.
- **DONE** `docs/SCALABILITY.md`, regenerated by
  `uv run python tools/benchmark.py --write`.
- **LIMIT** The benchmark measures a single process. The parallel claim is
  arithmetic from the linear per-person cost, since every person is scored
  independently — it is not a measured multi-core run.

### The honest half of the scalability answer

Compute scales; the caseload does not. The escalation rate is stable near 1%,
which at ten lakh personnel is roughly 8,200 cases a night — about 1,370
officers at six conversations each, more than a welfare cell can hold. That is an operating-point decision, and the evidence threshold
is the dial (0.65 → ~1.20%, 0.70 → ~0.65%, 0.80 → ~0.05%). Presenting the
compute figure without the caseload figure is the overclaim this project exists
to avoid.

---

## Phase 21 — Transfer and handoff (this phase)

- **DONE** `README.md` — a step-by-step "Running this on another device"
  section: prerequisites, install, verify, start, the no-browser CLI path, a
  Windows path, and a troubleshooting table ordered by what actually goes wrong.
- **DONE** `HANDOFF_PROMPT.md` — a brief to paste into an agent on a new
  machine: the invariants, the four bugs that were actually made, the
  technology choices that look like mistakes and are not, and the honest
  limitations.
- **DONE** This file.
- **DONE** Outlook readiness re-verified: `tools/portability_check.py` and
  `tools/package.py`.

---

## Phase 22 — Problem-statement audit (this phase)

Auditing the system line by line against the PS brief found three real gaps.
Full audit in [`docs/PS_COMPLIANCE.md`](PS_COMPLIANCE.md).

- **DONE — false negatives were not measured at all.** The PS names
  "minimizing false positives **and false negatives**" as a key challenge, and
  `calibration.propose` could only ever *raise* a threshold. Given enough quiet
  weeks it converges on naming nobody, which is indistinguishable from having
  no system. Built `pipeline/missed.py`: welfare concerns that surface through
  another channel are registered with the system's prior verdict and the gate
  that declined them, and above a 0.30 missed-case ceiling the loop proposes
  *loosening*. Three guard rails, all tested: a quiet week alone never loosens;
  both errors high at once never loosens; no proposal is applied by the thing
  that generated it. **Limit stated in code as `LIMITATION`:** this is
  surfaced-case recall, not recall.
- **DONE — no installable mobile app.** The PS asks twice for a "secure mobile
  application". `/me` was responsive but not installable. Added
  `web/app/manifest.ts` (standalone display, deep-links to `/me`, inline SVG
  icon so there is no binary asset to lose in transfer) and viewport/theme
  metadata. A web app rather than a store app so the force hosts and controls
  it end to end, and so there is one consent text rather than three.
- **DONE — no HRMS integration example.** `ingest/ports.py` defined the
  `Connector` protocol but only a replay implementation existed. Added
  `ingest/connectors/hrms.py`, reading a nightly export from a file share — no
  outbound connection, no credential in the analytics tier, no live dependency
  that can fail a welfare run. Nine tests, all about the boundary between
  *absent* and *zero*: `expected_rows` comes from the roster and not the file,
  a negative value is rejected rather than clamped to zero, a malformed row
  degrades the run rather than disappearing, and a sparse-by-nature domain can
  lower its expectation so the data-gap confounder does not fire forever.
- **PARTIAL — cyber-security.** No outbound calls, no credentials, hash-chained
  ledger. Encryption at rest, key management, segmentation and a penetration
  test need a deployment; there is no persistent store to encrypt yet. Listed
  as open rather than claimed.

---

## Phase 23 — Tech stack reconciliation and encryption at rest (this phase)

Checked the submitted deck's declared stack line by line against the tree. Full
map, fallbacks and judge Q&A in [`docs/TECH_STACK.md`](TECH_STACK.md).

**Result: 9 running · 5 substituted with the seam intact · 2 seams awaiting a
deployment · 1 not built.** Every substitution is the pendrive/email
constraint applied. Three things were wrong rather than merely different:

- **DONE — `sqlalchemy` and `aiosqlite` were core dependencies with an empty
  `db/` package.** Declared and unused. Now the foundation of the storage
  layer below, so the declaration is honest.
- **DONE — `pyproject.toml` claimed "the model layer prefers LightGBM when it
  imports". It did not.** Nothing read the `risk_model: "lightgbm"` flag.
  Implemented `tools/train_tabular.py --backend {auto,sklearn,lightgbm}`.
  Writing it exposed why the default is sklearn: LightGBM's wheel installs
  cleanly and dies at **load** with
  `dlopen(lib_lightgbm.dylib): Library not loaded: @rpath/libomp.dylib` — an
  `OSError`, not an `ImportError`, so the first version of the fallback crashed
  on exactly the machine it existed to protect.
- **DONE — `flwr`/`opacus` and `torch` extras are declared but never
  imported.** Not removed — they are the production target and the seams are
  Protocols — but each now says so in `pyproject.toml` instead of implying it
  runs.

### Encryption at rest (`src/samvedna/db/`)

The PS asks for "data anonymization and **secure storage** mechanisms"; the
first half was built from Phase 3 and the second half was an in-memory dict.

- **DONE** `db/crypto.py` — AES-256-GCM, one sealed blob per identity, **bound
  to its pid as additional authenticated data**. Without the AAD an attacker
  with write access moves one person's ciphertext onto another person's row and
  the system discloses the wrong name, with no key at all.
- **DONE** `db/keys.py` — `HsmKeyProvider` **refuses rather than faking it**;
  `KeyfileProvider` demands 0600 and a path outside the project tree (an
  in-tree key gets emailed inside the archive); `PassphraseProvider` is marked
  not-production-safe and live mode refuses it, checked twice.
- **DONE** `db/store.py` — SQLAlchemy 2.0, same schema on SQLite or
  PostgreSQL. The ledger is stored **in the clear on purpose** (integrity
  matters, confidentiality does not). `ConsentRow` has **no `withdrawn_at`
  column** — a nullable timestamp is something a dashboard can group by.
- **DONE** Three findings from the tests, each because the previous fix was not
  enough: `secure_delete` (SQLite's DELETE leaves the bytes in a freed page),
  `VACUUM`, and `wal_checkpoint(TRUNCATE)` — **the write-ahead log still held
  the purged pid** after the first two. Found by grepping the raw files.
- **DONE** One test nearly shipped worthless: it scanned only the `.db` file,
  where in WAL mode a fresh write has not landed yet, so it would have passed
  for the most reassuring possible reason — no data there at all. It now scans
  `.db` + `-wal` + `-shm` and asserts the pid *is* present.
- **DONE** 20 tests in `tests/storage/`. **No configuration writes an identity
  in the clear.**

### Two bugs the transfer check found, and their root causes

#### 1. `KeyfileProvider` corrupted 1 key in 21

**Symptom.** It read key material with `path.read_bytes().strip()`, and
`bytes.strip()` removes ASCII whitespace — so a random 32-byte key beginning or
ending with space, tab, newline, CR, VT or FF was silently shortened and
rejected. Measured at **4.7%**. In a deployment that is a key rotation with a
one-in-twenty chance of the system refusing to start; with a looser length
check it would instead have been a *different key*, encrypting data nothing
could later decrypt.

**Root cause: binary data put through a text operation.** `bytes` has all of
`str`'s tidying methods, so the line type-checks, reads as obviously
reasonable, and is wrong. Three fixes, at three depths:

- **DONE** The instance: `_decode_key_material` takes raw 32-byte keys
  verbatim and handles hex and base64 explicitly, so no encoding is guessed.
- **DONE** The test that should have caught it was probabilistic — it failed
  4.7% of the time, which is indistinguishable from flaky. Replaced with six
  parametrised tests covering every whitespace byte at both edges, plus a
  200-key round-trip (at a 4.7% rate that catches the old code with
  probability > 99.99%).
- **DONE** The class: `tests/core/test_binary_discipline.py` walks the AST of
  every module in `src/` and `tools/` and fails on a text-only method applied
  to the result of `read_bytes`, `b64decode`, `urandom`, `tobytes` or `digest`.
  It names the file and line. Verified by reintroducing the original line and
  watching it fail. Same idiom as the L3 purity and config-discipline guards:
  the discipline only holds if breaking it is noisy.

**Swept for others.** Every remaining `read_bytes()` in the tree feeds straight
into `hashlib.sha256`; both `.decode()` calls are inside try/except with an
explicit encoding; the voice path's `np.frombuffer` is guarded and returns 422
on an odd byte count. The only bytes-`.strip()` left in the repository is
inside the comment documenting this bug.

#### 2. `check.sh --transfer` could not fail

**Symptom.** It ran `pytest tests -q 2>&1 | tail -2`, and a pipeline exits with
the status of its last command — `tail`, always 0. The transferred copy failed
a test, printed "1 failed" on screen, and the gate still announced **ALL CHECKS
PASSED**. That is how the key bug above stayed hidden: it only failed in the
copy, and the copy could not report it.

**Root cause: `set -o pipefail` does not cross a process boundary.**
`check.sh` *did* set it — on line 14, for the shell that reads the file. Every
`run "..." bash -c '...'` block then started a **fresh shell with pipefail
off**, so the option was present, correct, and irrelevant. Verified directly:
`bash -uo pipefail -c 'bash -c "false | true"'` exits 0.

- **DONE** The mechanism: a `block()` helper that runs inline scripts as
  `bash -uo pipefail -c`. The options are passed on the command line, where a
  block added later cannot forget them. Every `bash -c` in the file is gone.
- **DONE** Two more masked statuses the same audit found:
  - The **fixtures determinism check** hashed `fixtures/*.json` before and
    after and compared — which reports "deterministic" on a tree with **no
    fixtures at all**, because both sides are the hash of an empty stream.
    Confirmed by hiding the directory: it passed. It now counts the files
    first, requires more than zero, and checks the count did not change.
  - The **offline REPLAY check** piped the run straight into `grep`, so a run
    that printed the Overnight line and then crashed would have passed. It now
    captures the log, judges the run's own exit status, then greps the file.
- **DONE** The class: `tests/core/test_shell_discipline.py` asserts every
  script sets `pipefail`, that `check.sh` spawns no bare `bash -c`, that
  `block()` exists and carries `-uo pipefail`, and that no `uv run` command has
  its status piped into `grep`/`tail`. Verified by reintroducing both original
  shapes and watching the guard name them.

**A gate that cannot fail is worse than no gate, because it is trusted.**

- **DONE — `.hypothesis` was shipping**: 112 of 294 archived files were
  Hypothesis's example cache. Excluded; the archive is now 182 files.

### Judge-facing material

- **DONE** [`docs/TECH_STACK.md`](TECH_STACK.md) — the map, the fallback table
  (what degrades vs. what fails closed), and 13 backup Q&A answers.
- **DONE** A 10-slide judging deck, published and rendered to a landscape PDF
  at `docs/artifacts/5-judging-deck.pdf`.

---

## Phase 24 — The console became usable end to end (this phase)

Four things a walkthrough found, none of which the 800-odd tests could see,
because every one of them was a join between two parts that were each correct.

- **DONE — the self-assessment sent nothing.** The form computed a band in the
  browser and stopped. Self-report is the only T1 domain and it was inert.
  Added `POST /api/me/{pid}/assessment`, scored on the server, with the acute
  item handled *before* any gate arithmetic.
- **DONE — "Save my choices" saved nothing.** Same shape: local receipt, no
  request. Every toggle read "allowed", the button read SAVED, and the server
  had never heard of it — so a submitted assessment was refused for want of
  consent that appeared to have been given. Two surfaces disagreeing about
  consent is the worst thing for them to disagree about.
- **DONE — the officer console was scoped to units that no longer existed.**
  Units gained their service abbreviation (`CRPF-01`) and the UI still asked
  for `UNIT-01`, so the caseload was empty and nothing errored. Scopes now
  derive from `/api/run`.
- **DONE — the voice add-on could never be unlocked.** `/me` recorded voice
  consent against the person's real pid; the voice routes asked whether
  `"SELF"` had consented. The refusal told the person to do the thing they had
  just done.

**DONE — `whoami` was not sticky.** It returned "the first MONITOR case", so
submitting an acute assessment escalated you out of the set and the next page
load handed the console a different person. Every symptom above looked like
persistence failing when it had worked perfectly for somebody the console was
no longer being.

---

## Phase 25 — Persistence, and the gate bug it exposed (this phase)

- **DONE** `db/journal.py` — an append-only event journal (consent,
  assessments, voice sittings), sealed with the same AES-256-GCM and key
  custody as the identity directory, replayed at startup. **It stores inputs,
  never derived verdicts**, so a threshold change in `config/` reaches
  somebody already decided.
- **DONE** Erasure reaches it: withdrawal deletes the rows and vacuums.
- **DONE** Degrades to nothing — no crypto library, no key, or
  `persist_state=False` and the system runs exactly as before.
- **DONE — the persistence gate treated *absent* as *zero*.** A domain with no
  history for a window contributed nothing to the numerator and its full
  weight to the denominator, diluting every domain that did have history. A
  jawan submitting a severe self-assessment pushed their own persistence from
  0.650 (passing) to 0.505 (failing) — **reporting distress made the system
  less likely to act.** Twelve of 125 monitored cases flipped that way.
- **DONE — and `_with_self_report` was destroying history.** 52 of 125 cases
  already carried self-report history; it was replaced rather than merged.
  `{7: 1.0, 30: 1.0, 90: 0.656}` became `{7: 1.0}`.
- **DONE** The correct model came from the instrument: **PHQ-9 asks "over the
  last 2 weeks"**, so a breaching score is a statement about a fortnight, not
  a day. Recording it as "1 day in 7" understated what was asked. Two earlier
  attempts at the fix were wrong in opposite directions and are documented at
  the call site.
- **Result:** no gate now ever flips PASS→FAIL from submitting, persistence
  never falls, and the published calibration figures are unchanged — in those
  rows every domain has all three windows, so the new rule reduces to the old
  formula exactly. There is a test asserting that.

---

## Phase 26 — Transfer, split, and the copilot brief (this phase)

- **DONE — a browser tab broke `run.sh`.** `lsof -ti :3100` returns every
  socket on the port, and an open console tab contributes an ESTABLISHED
  client socket owned by Chrome — so with the dev server running normally,
  `--status` reported the port "held by something that is not ours" and
  `--stop` refused to free it. Fixed with `-sTCP:LISTEN` behind a single
  `listeners_on()` helper, because two call sites are two chances to forget.
  `tests/core/test_shell_discipline.py` now fails on a port query without the
  flag, and on a second definition of it.
- **DONE** `tools/mailsafe.py --split N` and `--merge`. Every part carries the
  **whole-file** checksum, not its own: the only question after a merge is
  whether the reassembled file is the one that was sent, and a per-part
  checksum cannot answer it. A wrong merge can still unzip partially, which is
  worse than failing outright.
- **DONE** `tools/export_dataset.py` — the cohort as CSV for judges, with
  `latent_strain` beside `label_positive` so the circularity is visible by
  sorting two columns. Records are sampled: the full set is 3.1 million rows
  and 250 MB, which would fail the archive's own size check.
- **DONE** `TRANSFER.md` — sending, receiving, merging, and briefing an AI
  assistant, including the five things one will get wrong unless told.

---

## Open

Everything here needs something this project does not have, and none of it can
be closed by writing more code.

| # | What | Why it is open |
|--:|---|---|
| 1 | **Validation on real cohort data** | There is no real dataset. The cohort is generated from seed 26186 and the training label is `strain >= 0.55`, which is circular — the model learns the generator. Any accuracy figure from it measures the generator, not the world. The model card is stamped `synthetic: true`. Needs an ethics approval and a data-sharing agreement, not an afternoon. |
| 2 | **Persist the audit ledger** | State survives a restart; the ledger does not — it is rebuilt from the nightly run, so human actions taken before a restart are absent. Journal the entries with their original timestamps and hashes so the chain verifies across processes. About an hour, and the only known gap in the restart story. |
| 3 | **Clinical instrument licensing** | PHQ-9 is implemented with real items and real scoring. Validated translations cannot be invented; the locale files refuse to serve an instrument translation that has not been supplied. Needs the licence holder. |
| 3 | **Threshold calibration against a real welfare cell** | The operating point should be set by how many conversations a specific cell can hold. The dial is exposed and the curve is measured; the decision is a command one. |
| 4 | **Feature-store tables on TimescaleDB** | The identity, ledger and consent tables are built and encrypted (`db/store.py`). The *feature store* is still in-memory: it is the volume that wants TimescaleDB's compression and continuous aggregates, and a half-tuned hypertable definition would be worse than the seam. REPLAY keeps an in-memory synthetic directory by default, because no demonstration may depend on live service-record access. |
| 5 | **Multi-core benchmark** | The parallel claim is arithmetic from the measured linear per-person cost, not a measured multi-core run. |
| 7 | **Deployment hardening** | Encryption at rest, key custody and erasure are built and tested. Network segmentation, OS hardening, key *rotation* and a penetration test are deployment activities, not code. |
| 6 | **Shadow-mode field trial** | Phase 1 of the deployment plan issues no alerts at all. That is a deployment activity. |

---

## What must not be broken

The short version of `HANDOFF_PROMPT.md`, because these are the things a
well-intentioned change breaks:

1. No model, LLM or heuristic may emit a gate value, a verdict or a confidence.
2. `core/` stays pure — enforced by an AST test.
3. Actionability stays multiplicative. Its factors are vetoes, not votes.
4. Verdict precedence stays consent → actionability → persistence →
   evidence/consistency → ESCALATE.
5. The acute override keeps bypassing the gates.
6. Mind-change text stays computed by inverting the failed gate.
7. A commanding officer keeps seeing no individual, at any group size.
8. The refused list stays auditor-only.
9. No PII, no organisation names, no absolute paths, no external endpoints.
10. Any mutation of `Series.points` goes through a method that invalidates the
    ordered mirror. There is exactly one, and it is `drop_before`.

---

## How to verify all of it

```bash
./check.sh                                        # lint · 729 tests · purity · portability · packaging
./check.sh --transfer                             # ...and prove it runs from a copy, cold
uv run python tools/benchmark.py --write          # regenerate docs/SCALABILITY.md
uv run python tools/portability_check.py          # PII, org names, absolute paths, endpoints
uv run python tools/package.py                    # the emailable archive
```
