# Tech stack — declared, built, and where each piece runs

Three things in one document:

1. **The map** — every technology in the submitted deck, whether it is running,
   and which file it runs in.
2. **The fallbacks** — what happens when each component fails.
3. **The Q&A** — the tech-stack questions a judge will actually ask, with
   answers that hold up.

The deck was written before the build. Nine of its choices changed, every one
for the same reason, and that reason is worth saying first because it answers
most of the questions below at once:

> **The system had to survive being copied onto a pendrive and emailed.** No
> installer, no network at run time, no native compiler on the recipient's
> machine. Every substitution below is that constraint applied.

Nothing was dropped. Every declared technology is either running, installable
as an optional extra, or sitting behind a `Protocol` seam that a caller cannot
distinguish. **The declared stack is the production target; the built stack is
what runs from a copied folder.**

---

## 1. The map

### Data & backend

| Declared | Status | Where it runs |
|---|---|---|
| **Python 3.12** | **Running** (3.11+; developed on 3.14) | Whole backend. `pyproject.toml` sets `requires-python = ">=3.11"` |
| **FastAPI** | **Running** | `api/app.py` — 21 routes; `api/voice_routes.py` — 5 more; `api/api_console.py` — a self-contained API console at `/api-console` (FastAPI's own `/docs` pulls Swagger UI from a CDN and renders blank air-gapped) |
| **PostgreSQL + TimescaleDB** | **Seam built, SQLite default** | `db/store.py` — SQLAlchemy 2.0 models. Same schema on either; change `database_url`. TimescaleDB is for the feature-store volume, which is deliberately not shipped as a half-tuned hypertable |
| **Apache Airflow** | **Substituted** | `pipeline/dag.py` — a nine-stage DAG with per-stage timings, row counts and status. Airflow needs a scheduler, a metadata database and a web server; the workload is one nightly batch |
| **Redis** | **Substituted** | `disclosure/dpcache.py` — the release cache Redis would have held. In-process, because there is one process |

### Predictive models

| Declared | Status | Where it runs |
|---|---|---|
| **XGBoost / LightGBM** | **Supported, not default** | `tools/train_tabular.py --backend {auto,sklearn,lightgbm}`. `auto` prefers LightGBM when it *loads* and falls back to scikit-learn. Default is `sklearn.GradientBoostingClassifier` |
| **Temporal Transformer** | **Substituted** | `analytics/models/sequence.py` — explicit roster-rhythm features, plus a multiplicative sustainability term that separates *predictable* from *sustainable*. torch is ~2 GB |
| **Survival analysis** | **Running** | `analytics/models/survival.py` — discrete-time hazard, giving a "by when" rather than a "how bad" |

### Explainability

| Declared | Status | Where it runs |
|---|---|---|
| **SHAP** | **Running** | `analytics/attribution.py` — TreeExplainer; `api/app.py` `_plain_driver()` translates a feature name into a sentence an officer can repeat |
| **Deterministic gate engine** | **Running** | `core/gates.py`. Pure — an AST test fails the build on I/O, a clock, `random` or `numpy` |
| **Immutable audit ledger** | **Running** | `disclosure/audit.py` — append-only, hash-chained; persisted by `db/store.py`. A failed write aborts the disclosure |

### Privacy stack

| Declared | Status | Where it runs |
|---|---|---|
| **Flower (federated)** | **Substituted, extra available** | `analytics/models/federated.py` — FedAvg with clip-then-noise ordering. `uv sync --extra federated` installs Flower; the aggregation seam is a `Protocol` |
| **Opacus (DP)** | **Substituted** | `ingest/dp.py` — calibrated noise with a finite ε budget (60ε total, ~24ε per unit heat map) |
| **k-anonymity** | **Running** | `disclosure/kanon.py` — k≥5, **suppress not round** |
| **AES-256 + HSM** | **AES-256 running; HSM is a seam** | `db/crypto.py` — AES-256-GCM, one sealed blob per identity, **bound to its pid as AAD**. `db/keys.py` — `KeyfileProvider` (0600, outside the tree) and `HsmKeyProvider`, which **refuses rather than faking it** |

### Apps & access

| Declared | Status | Where it runs |
|---|---|---|
| **Flutter (Android/iOS)** | **Substituted** | `web/app/manifest.ts` — installable PWA, `display: standalone`, deep-links to `/me`. One codebase and **one consent text** |
| **React + TypeScript** | **Running** | `web/` — React 19, TypeScript, Next.js 15.5.4 App Router. Four consoles |
| **Keycloak RBAC** | **Substituted, seam intact** | `disclosure/rbac.py` — five roles, purpose binding, unit scoping, enforced in the API not the interface. Keycloak issues tokens; the grant table still decides |
| **On-prem Kubernetes** | **Not built** | Single process, two ports. `run.sh`. K8s is a packaging decision for a data centre, and a Helm chart nobody has run against a real cluster is a liability |

**Score: 9 running · 5 substituted with the seam intact · 2 seams awaiting a
deployment · 1 not built.**

---

## 2. Fallbacks — what happens when each part fails

The governing rule, and it is the opposite of most systems: **this system fails
towards silence, never towards accusation.** A degraded input must never become
a name on an officer's screen. But a degraded input must also never be
*invisible* — every fallback below is reported, none is silent.

### Failures that degrade the run

| What fails | What happens | Where |
|---|---|---|
| **The risk model is missing or won't load** | Stage 5 degrades; the run continues. The gates never needed a score — it is an input, not the decision. Proven in CI: `samvedna run --model-dir /nonexistent` still escalates | `pipeline/dag.py` stage 5 |
| **LightGBM won't load** (`libomp` missing) | `--backend auto` prints `lightgbm unavailable (OSError); using scikit-learn` and trains. Explicitly requesting `--backend lightgbm` **fails loudly** — somebody who asked for it needs to know they did not get it | `tools/train_tabular.py::_make_booster` |
| **An HRMS connector returns short** | The shortfall is reported as `missing_fraction`, the data-gap confounder fires, and the domain is **excluded rather than imputed**. Run status becomes `PARTIAL` and the officer's header says so | `ingest/connectors/hrms.py` |
| **An HRMS export file is absent** | Status `unavailable`, not `ok`-with-zero-rows. "The clerk has not filed" must never read as "nobody worked this month" | same |
| **A malformed row in an export** | Counted, dropped, run marked `partial`. Never coerced — a duty-roster reading of −3 hours is a broken extract, and clamping it to zero turns somebody else's bug into a welfare finding | same |
| **A reviewer times out** | Recorded in `unavailable_reviewers`; the run degrades rather than silently passing the case. A missing Confounder Check is the *most* dangerous one to skip, so its absence is on the case card | `analytics/reviewers/panel.py` |
| **Model drift exceeds the PSI threshold** | **Escalation freezes entirely.** No names are released until a governance board reviews. The officer's console shows the freeze reason | `pipeline/dag.py`, `config/thresholds.py` |

### Failures that stop the run

These fail closed on purpose. There is no degraded mode.

| What fails | What happens | Why not degrade |
|---|---|---|
| **The audit ledger write fails** | The disclosure it was recording **aborts**. The name is not looked up | There must be no ordering in which a name exists without a record of it |
| **The encryption key is missing** | `open_store` raises `InsecureConfiguration`. The system does not start | A store that degrades to plaintext under misconfiguration is worse than one that stops, because the operator never finds out |
| **A dev key in live mode** | Refused: `mode=live with passphrase:scrypt (NOT production safe)` | Checked twice, in `provider_from_settings` and again in `open_store` |
| **The keyfile is inside the project tree** | Refused | It would be committed, then zipped and emailed with the archive |
| **The keyfile is group- or world-readable** | Refused — must be 0600 | AES-256 with a readable key is a filing cabinet with the key taped to the lid |
| **A ciphertext moved to another pid** | `InvalidTag`. Refused | The pid is the AAD. Without it, GCM decrypts happily and the system discloses **the wrong person** — an attack that needs no key at all |
| **A pid from a rotated-out salt epoch** | Resolves to `None` | A rotated pid is not the same pid. Resolving it discloses a stranger |
| **The DP budget is exhausted** | Aggregate views stop being served. **Individual welfare decisions are unaffected** | The budget protects group statistics, not welfare |
| **Consent is absent** | `NO_FLAG`, first in the verdict precedence, before any gate arithmetic runs | Consent is not a factor to be outvoted by a strong score |

### Infrastructure fallbacks

| Layer | Primary | Fallback |
|---|---|---|
| Database | PostgreSQL + TimescaleDB | SQLite, same schema, same code — change one URL |
| Key custody | HSM / KMS | 0600 keyfile outside the tree; passphrase+scrypt in replay only |
| Identity store | Encrypted SQLite/Postgres | In-memory (REPLAY, synthetic identities, never written to disk) |
| Connectors | HRMS export on a share | `ReplayConnector` over fixtures — the full pipeline runs with no records access at all |
| Web console | Next.js on the network | CLI: `samvedna run`, `samvedna cohorts`, `samvedna case <pid>` |
| Mobile | Installable PWA | Any browser; the consoles are responsive |
| Fonts | System font stacks | *No fallback needed — there is no webfont.* A CDN link fails silently in an air-gapped data centre and announces the deployment to a third party in one that isn't |

---

## 3. Backup Q&A — the tech-stack questions, answered

### "Your deck says LightGBM. `pip list` shows scikit-learn. Which is it?"

Both. `--backend auto` prefers LightGBM and falls back. The default is
scikit-learn, and here is the actual reason, reproduced on the development
machine:

```
dlopen(.../lib_lightgbm.dylib): Library not loaded: @rpath/libomp.dylib
```

The wheel installs cleanly and dies at *load*, because `libomp` is a separate
Homebrew package. That is an `OSError`, not an `ImportError` — so the naive
`except ImportError` fallback does not catch it, which we found by writing it
wrong first. Same algorithm family, SHAP's TreeExplainer supports both, and the
model card records which one produced the artefact.

**If pressed:** on a provisioned server, `uv sync --extra fast` and you get
LightGBM. The choice is per-deployment, not baked in.

### "Where is Airflow?"

`pipeline/dag.py`. Airflow's value is scheduling many interdependent DAGs
across a cluster; the workload here is one nightly batch, and Airflow's own
footprint is a scheduler, a metadata database and a webserver. What was needed
from it — per-stage status, row counts, timings, and a visible failure instead
of a silent one — is 400 lines and visible on `/demo`. `cron` triggers it.

### "No Redis? How do you cache?"

`disclosure/dpcache.py`, in-process, because there is one process. And the
cache is not a performance optimisation — it is a **security control**. Fresh
differential-privacy noise on every refresh averages back to the truth, so a
repeated view is served from cache and charged to the ε budget once. Without
it, the refresh button is an averaging attack. Redis would hold the same
structure if this ran multi-node.

### "Flutter was declared. This is a web app."

A PWA, installable, `display: standalone`, deep-linking to `/me`. Two reasons,
and the second is the real one:

1. **The force hosts it.** A store app passes through Apple's and Google's
   review and update channels, so the binary sits outside the organisation.
2. **One consent text.** Consent is recorded against a specific text in a
   specific language at a specific version — it is legally load-bearing.
   Maintaining that screen three times across web, iOS and Android is three
   chances for them to disagree about what somebody agreed to.

### "Is the data actually encrypted, or is that on a slide?"

Actually. And the test that proves it greps the raw database files for the
plaintext:

```
tests/storage/test_secure_store.py::test_no_personal_data_appears_in_the_database_file
```

It scans the `.db`, the `-wal` and the `-shm`, and asserts that `Arjun`,
`Sharma`, `CAPF-000001` and the contact number are all absent while the pid
*is* present — because a scan that finds nothing proves nothing if the row
never reached the file. That version of the test nearly shipped.

**AES-256-GCM, one sealed blob per identity, bound to its pid as additional
authenticated data.** The AAD is the part worth mentioning: without it, an
attacker with write access swaps one person's ciphertext onto another person's
row and the system discloses the wrong name — with no key at all.

### "What about the HSM? Do you have one?"

No, and `HsmKeyProvider.key()` raises rather than pretending:

> "HSM support is a seam, not an implementation."

Every HSM answers a different protocol — PKCS#11, KMIP, a sovereign cloud KMS
— and a stub that quietly returned a locally-derived key while calling itself
an HSM provider would be the most dangerous class in the codebase. Until a
force names its module, `KeyfileProvider` requires 0600 and a path outside the
project tree, and refuses both otherwise.

### "You said erasure. SQLite's DELETE doesn't erase."

Correct, and that is a bug we found in our own test. Three steps now:

1. `PRAGMA secure_delete = ON` zeroes the row's bytes rather than marking the
   page free.
2. `VACUUM` rewrites the file without the freed pages.
3. `PRAGMA wal_checkpoint(TRUNCATE)` — **because the write-ahead log still held
   the frames.** After steps 1 and 2 the purged pid was still greppable out of
   the `-wal` sidecar.

Under the DPDP Act erasure has to mean erasure, and "unlinked from the b-tree"
is not that.

### "Can I see the API itself, not just the dashboards?"

`http://localhost:8090/api-console` — every operation, the role each one needs,
and a Send button per route. Switch role in the dropdown, re-send the same
request, watch it turn 403.

It is served by the Python process with **no CDN, no webfont and no outbound
request**, because FastAPI's own `/docs` loads Swagger UI from
`cdn.jsdelivr.net` and `/redoc` also pulls Google Fonts — both render as a
blank page on an air-gapped network, which is the network this system is built
for and also, frequently, the wifi at a venue. `/docs` is still mounted for
anybody who has internet and prefers it.

The console also knows something Swagger UI cannot: which role each route
requires. From the terminal, the same demonstration in two lines:

```
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Role: auditor'          -H 'X-Operator: aud-01' -H 'X-Units: '        localhost:8090/api/refused   # 200
curl -s -o /dev/null -w '%{http_code}\n' -H 'X-Role: welfare_officer'  -H 'X-Operator: wo-01'  -H 'X-Units: UNIT-01' localhost:8090/api/refused   # 403
```

No role at all returns **401**, not 403 — the API distinguishes "who are you"
from "I know who you are, and no". Full command list in the README under
*Showing the backend, if a judge asks*.

### "Keycloak?"

`disclosure/rbac.py` holds the grant table — five roles, purpose binding, unit
scoping — and it is enforced in the API, not the interface. Keycloak's job is
issuing and validating tokens; it does not decide whether a welfare officer may
see a refused case. Put Keycloak in front and the grant table still decides.
Try it live: sign in as a welfare officer and open `/audit` — the API returns
403 and the page **explains the refusal** rather than hiding.

### "Kubernetes? On-prem?"

Not built, and I'd rather say that than show you a Helm chart nobody has run
against a real cluster. It runs as one process on one server. `docs/SCALABILITY.md`
has the measurement: **7.7 ms per person, sub-linear across a 16.7× range**, so
ten lakh personnel is 2.1 hours on one core. There is no distributed system
here because the workload does not need one — every person is scored
independently of every other.

### "Which parts are AI, and which parts decide?"

The split is the architecture:

- **AI:** gradient-boosted risk score, SHAP attribution, survival hazard,
  roster-rhythm features, three reviewers.
- **Decides:** `core/gates.py`. Four sums against four thresholds.

**No model, LLM or heuristic may emit a gate value, a verdict or a
confidence.** There is no LLM in the decision path and no external endpoint
anywhere — `tools/portability_check.py` fails the build on one. `core/` is
pure; an AST test parses every module and rejects I/O, a clock, `random` and
`numpy`.

### "Why Next.js 15 and React 19 — isn't that risky for a demo?"

It is pinned in `package-lock.json`, which ships. The version that built the
demo is the version that builds on the judge's machine. The lockfile is why
`./check.sh --transfer` can unzip into a temp directory and get a working
console.

### "How do I know the demo isn't hardcoded?"

`uv run samvedna cohorts` runs all three fixture cohorts through the real
engine, and the interesting one **refuses** — consistency `0.694` against a
`0.700` threshold, because 45–61% of that unit is deviating the same way. A
hardcoded demo would not fail by 0.006. And `./check.sh` includes a check that
the fixtures reproduce byte-for-byte from the seed.

### "What is your biggest weakness?"

Two, and I would rather name them than have them found.

1. **There is no real dataset.** The cohort is generated from seed 26186 and
   the training label is `strain >= 0.55`, which is circular — the model learns
   the generator. The model card is stamped `synthetic: true`. Any accuracy
   figure from it measures the generator, not the world.
2. **The caseload does not scale even though the compute does.** The escalation
   rate is stable near 0.8%, which at ten lakh personnel is ~8,200 cases a
   night and ~1,370 welfare officers at six conversations each. That is not
   deployable. It is a threshold decision, not an engineering one, and the dial
   is exposed and measured: 0.65 → ~1.20%, 0.70 → ~0.65%, 0.80 → ~0.05%.

### "What would you build next?"

The false-negative instrument already exists (`pipeline/missed.py`) but has no
data — it needs a field trial to populate. Then encryption key rotation, and a
penetration test. Not more models: the models are not the constraint.

---

## Verify any of this

```bash
./check.sh                                  # lint · 729 tests · purity · portability · packaging
./check.sh --transfer                       # unzip into a temp dir and run cold
uv run pytest tests/storage -v              # the encryption-at-rest claims
uv run python tools/train_tabular.py --backend lightgbm   # watch it refuse, with the reason
uv run python tools/benchmark.py --write    # regenerate the scalability numbers
uv run samvedna cohorts                     # the refusal, computed not scripted
```
