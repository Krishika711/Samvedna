# SAMVEDNA

**AI-based predictive personnel stress and welfare monitoring for uniformed forces.**
SIH 2026 · PS 26186 · MedTech/BioTech/HealthTech · Team CodeZila

> **The model raises the concern. The evidence must corroborate it.
> The arithmetic makes the decision. A human welfare officer takes the action.**

SAMVEDNA identifies early indicators of stress, burnout and emotional fatigue
among CAPF and Armed Forces personnel from records the organisation already
holds, plus voluntary self-assessment, and routes welfare recommendations to
authorised welfare officers.

Hundreds of systems can produce a risk score and a dashboard. This one is built
around a different claim:

> **A risk score is not a decision. Nothing reaches a human until the evidence
> earns it.**

Every candidate signal passes four computed gates. If they do not all clear, the
system produces **no name** — only a MONITOR record and a machine-computed
statement of exactly what additional evidence would change the decision.

---

## Run it

Nothing below needs a network, a database, a credential or a GPU. REPLAY is the
default mode, so no demonstration can depend on live service-record access.

```bash
uv sync --all-extras
cd web && npm install && cd ..

./run.sh            # builds the console, starts both servers, verifies, prints the URL
./run.sh --stop     # stop both
./run.sh --status   # what is listening
```

Then open **http://localhost:3100/demo** — the control room. It shows what the
overnight run actually did (stage timings, funnel counts, ledger head, all read
live from `/api/run`) and has one door into each of the four consoles, switching
you into the role that console needs.

The four consoles are the system, not a description of it:

| Console | Route | The job it does |
|---|---|---|
| **Welfare officer** | `/officer` | Clear the queue. Reveal identity, record contact, close out. |
| **Commanding officer** | `/unit` | Read unit strain. Aggregates only — no individual, ever. |
| **Governance auditor** | `/audit` | Review every verdict *including the refusals*, verify the chain, watch the privacy budget. |
| **Personnel** | `/me` | Own consent, own drivers, own check-in, withdrawal. Eight languages. |

Try a door you are not signed in for. The refusal is explained rather than
hidden, which is the same behaviour the API has.

The backend has its own console at **http://localhost:8090/api-console** —
every route, the role each needs, and a Send button. See *Showing the
backend* below.

Ports are overridable, because 3000 is the default for every Next project on a
machine and this one should not have to win that race:

```bash
SAMVEDNA_WEB_PORT=4000 SAMVEDNA_API_PORT=8091 ./run.sh
```

`run.sh` frees a port only when what holds it is ours, and waits until the
console's **stylesheet** resolves rather than just its HTML — a page that
returns 200 while its stylesheet 404s renders as raw browser defaults, which
looks exactly like a broken design and is not one.

Or drive it from the command line, with no web layer at all:

```bash
uv run samvedna run                       # a full nightly pipeline, offline
uv run samvedna cohorts                   # the three fixture cohorts through the gates
uv run samvedna case pid-mon-0001         # one case, with the arithmetic shown
```

Optional, and the system runs without them:

```bash
uv run --extra ml python tools/train_tabular.py   # tabular + survival models
./check.sh                                        # lint, tests, portability, packaging
./check.sh --transfer                             # ...and prove it runs from a copy
```

---

## What a run looks like

```
Overnight: 240 screened · 128 deviating · 128 reviewed · 3 escalated

  evidence       ████████████████████ 1.000 / 0.65  PASS
                 evidence = 0.50x1.000 + 0.30x1.000 + 0.20x1 = 1.000
  consistency    ██████████·········· 0.694 / 0.70  FAIL
                 consistency = mean(0.667, 0.708, 0.708) = 0.694

  what would change our mind:
    [consistency] 0.694 -> needs 0.70
      · the duty_roster deviation is still present after the unit's current
        deployment cycle ends (op-tempo confounder, 0.70)
```

That case is sustained, multi-domain and strongly deviating — and **produces no
name**, because 61% of the unit shows the same pattern and the unit is deployed.
The finding is correctly reframed as a command workload problem.

---

## Architecture

Dependencies point downward only.

| Layer | What lives there |
|---|---|
| **L6 Presentation** | Officer console · commander unit view · personnel app · audit console |
| **L5 Access & disclosure** | RBAC · purpose binding · k-anonymity · consent — **the only layer that can re-identify** |
| **L4 Orchestration** | Nightly pipeline, state machine, run records |
| **L3 Decision domain** | gates · verdict · mind-change · confounders — **pure, no I/O, no clock, no model** |
| **L2 Analytics** | Feature store · risk models · attribution · reviewers |
| **L1 Privacy & ingest** | Connectors · pseudonymisation · differential privacy · federated client |

L3 purity is enforced by a test that parses every module in `core/` and fails on
an import of `sqlalchemy`, `httpx`, `torch`, `numpy`, `asyncio`, `time`,
`random`, `os` or `logging`, or on any `samvedna.*` import outside `core` and
`config`.

---

## The four gates

Thresholds and weights live in `config/`; a test parses `core/` and fails on any
policy number that escaped.

| Gate | Asks | Threshold |
|---|---|---|
| **Evidence** | Is there enough corroborated signal to be talking about a person at all? | 0.65 |
| **Consistency** | Do the domains agree, or is one anomaly shouting? | 0.70 |
| **Persistence** | Sustained, or a bad week? | 0.60 |
| **Actionability** | Is there a welfare action that fits, that is not already being taken? | 0.50 |

Actionability is **multiplicative, not a weighted sum**, and that is not a style
choice. Three of its terms are hard vetoes. With plausible weights, a person who
never consented to being contacted scores 0.85 and clears a 0.50 threshold — the
gate would leak, in the one direction that matters. `test_a_weighted_sum_would_leak`
pins that argument as a test.

**Verdict precedence** — irrecoverable conditions before recoverable ones, so a
person with no consent basis is closed rather than described as "not yet
sustained", which would be an invitation to wait for them:

```
consent absent → NO_FLAG · actionability failed → NO_FLAG
persistence failed → MONITOR · evidence or consistency failed → MONITOR
otherwise → ESCALATE
```

**The safety override** bypasses persistence and evidence when a validated acute
item is endorsed. It is triggered by the **instrument**, never by a model score;
it routes to a mental-health authority, **never** to the chain of command; and the
gates it bypassed are still computed and recorded.

---

## DPDP Act 2023 — obligation to module

Implemented as code paths, not policy documents.

| DPDP obligation | Where it is satisfied | How it is checked |
|---|---|---|
| **Purpose limitation** (§4, §8(1)) | `disclosure/rbac.py` — every grant is a (role, purpose) pair; ACR, promotion, posting and disciplinary purposes are **enumerated and refused for every role** | `test_no_role_may_ever_act_for_an_administrative_purpose` |
| **Data minimisation** (§8(3)) | `ingest/normalise.py` — unconsented domains are discarded, not marked. `Identity` carries no psychometric field | `test_the_consent_filter_drops_unconsented_domains`, `test_the_identity_carries_no_psychometric_content` |
| **Consent, granular** (§6(1)) | `disclosure/consent.py` — per-domain scope plus an independent welfare-contact toggle | `tests/privacy/test_consent_lifecycle.py` |
| **Consent, withdrawable** (§6(4)–(6)) | `ConsentRegistry.revoke` → purge, drop from watchlists, cancel undelivered alerts, within one cycle | §8.12 criterion 1 |
| **Erasure** (§12(3)) | `PurgeResult` and `complete_revocation` — self-report and biometric rows purged, ledger entries retained (they hold no content) | `test_after_the_purge_the_person_is_simply_not_enrolled` |
| **No detriment for withdrawal** (§6(6)) | Revocation has exactly one accessor, named `revocations_for_auditor`. No count, rate or per-unit view exists to be read | `test_revocation_is_visible_to_the_auditor_and_to_nobody_else` |
| **Security safeguards** (§8(5)) | HMAC pseudonymisation under a rotating salt; identifiers never reach L2/L3 | `tests/privacy/test_pseudonymisation.py` |
| **Accuracy** (§8(3)) | Workflow G — a person can contest a driver; a factual error becomes a correction request to the records custodian | `test_a_factual_error_becomes_a_correction_request` |
| **Accountability** (§8(4)) | Append-only hash-chained ledger; a failed write aborts disclosure | §8.12 criteria 7 and 8 |
| **Notice** (§5) | `/me` — "what the system can and cannot see about me" is the page, not a link, in eight languages | `web/app/me/page.tsx` |
| **Informed consent** (§6(1), §6(3)) | A `ConsentReceipt` records the locale, text version and SHA-256 of the exact strings shown, so "agreed to what, in what words?" has an answer | `tests/privacy/test_consent_text.py` |

---

## Vernacular consent

Eight languages — **English · हिन्दी · বাংলা · मराठी · தமிழ் · తెలుగు · ਪੰਜਾਬੀ ·
اردو** — covering the whole personnel surface, each offered in its own script.
Urdu is right-to-left, so that path is exercised rather than assumed.

Three rules, each because the ordinary i18n approach would be harmful here:

- **A missing key is a build failure, not an English fallback.** Falling back
  puts an English sentence under a Hindi heading; a person who skips the line
  they cannot read has not given informed consent, and nothing records it.
  `tools/check_locales.py` runs in `check.sh`.
- **An unreviewed translation cannot ground consent.** A `draft` locale is
  refused with a reason, and a refused consent enrols nobody. Seven of the eight
  are currently drafts: complete and structurally verified, but not yet read by a
  native speaker. `--strict` fails on any draft, which is what production runs.
- **A validated instrument's translation is never invented.** PHQ-9 cut-offs mean
  what they mean only in the wording they were validated in, so the app offers
  the questionnaire where a licensed translation exists and says so plainly where
  it does not.

```bash
uv run python tools/check_locales.py            # completeness
uv run python tools/check_locales.py --strict   # ...and no drafts
```

## Privacy properties, and how each is checked

- **No identifier reaches the model layer.** Pseudonymisation is at ingest,
  before features. Proved by scanning every emitted record against the roster.
- **A commander payload contains no pid.** `Cell` has no field one could live in
  — there is no drill-down to hide because there is nothing to drill into.
- **k ≥ 5, suppress not round.** A rounded cell still tells you it was not zero,
  and a suppressed cell does not leak its true `n` either.
- **A refresh is not an averaging attack.** Released cells are cached per
  (unit, date, label). Ten refreshes of a view draw one noise sample, not ten —
  otherwise their mean is the truth and the budget only buys the attacker samples.
- **The privacy budget runs out.** An exhausted budget withholds cells rather
  than releasing them un-noised, and the caller cannot reset it.
- **Federated updates carry parameters and a count.** Clipped to a fixed L2 norm
  *then* noised — the other order clips the noise too and leaves a campaign
  reporting an epsilon it never achieved.

---

### Add-on: voice concordance

Not part of the submitted scope. The system reads service records, voluntary
self-assessment and an opt-in wearable; voice was added afterwards as a further
way of understanding, and is tiered T3 so it corroborates a case and can never
make one. No connector can fetch a voice — it comes only from a consented
sitting, no audio is ever stored, and the transcript is destroyed when the
session closes.

## Testing

```bash
./check.sh              # lint · tests · portability · determinism · offline run · packaging
./check.sh --transfer   # unpack into an unrelated directory and run it cold
uv run python -m pytest tests/workflow/test_acceptance_812.py -v   # the eight criteria
```

`tests/property/` holds Hypothesis invariants: adding a confounder never raises
consistency, adding a corroborating domain never lowers evidence, extending a
breach never lowers persistence, identical input always yields an identical
verdict, the composite never affects the decision, and no ESCALATE is ever
produced without consent covering a deviating domain.

---

## Transferring this project

It is self-contained: no imports, paths or files from any sibling project, and no
third-party import that is not declared in `pyproject.toml`. Both are enforced.

```bash
uv run python tools/package.py            # a clean archive, size-checked for email
uv run python tools/portability_check.py  # absolute paths, emails, org names, credentials
./check.sh --transfer                     # prove it runs from the copy, cold
```

`tools/package.py` excludes every rebuildable directory, refuses to build if the
portability check fails, rejects file types mail gateways block, and fails if the
archive exceeds the attachment limit. The lockfile **does** ship — it is what
makes the copy resolve to the same versions as the original.

### If the mail gateway blocks the zip

It probably will, and the archive being clean does not help. `package.py`
answers "is anything *inside* this dangerous"; a gateway asks "is a zip allowed
at all", and for most corporate Exchange and Defender policies it is not. When a
scanner does look inside, it applies the same extension blocklist there — this
tree carries 116 `.py`, 3 `.sh`, 1 `.js` and 1 `.mjs`, and `.js` is on
Microsoft's default list with `.sh` and `.py` added by most organisations.

Renaming the file does not work: content inspection recognises the `PK\x03\x04`
header whatever the extension says. Password-protecting it makes things worse —
a scanner that cannot inspect an archive usually quarantines it.

So stop sending an archive:

```bash
uv run python tools/package.py      # build the archive
uv run python tools/mailsafe.py     # -> dist/samvedna-<date>.zip.txt
```

Attach the `.txt`. It is base64: inert ASCII text with no zip header to
recognise, no blocked extension, and nothing executable to scan. It costs 33%
in size — 2.7 MB becomes 3.6 MB, still far inside any limit.

The file carries its own decode instructions in a plain-text header, written for
somebody who has never seen this project and therefore uses only tools that ship
with the OS (`base64` on macOS/Linux, PowerShell on Windows), plus a SHA-256 so
they can prove it arrived intact. If they *do* have the project:

```bash
uv run python tools/mailsafe.py --decode samvedna-<date>.zip.txt
```

That verifies the checksum and refuses to write the archive if the body was
altered in transit — which matters, because a gateway that helpfully rewraps a
message body produces a file that unzips far enough to look fine.

**Better still, if your organisation allows it:** put the archive on
OneDrive/SharePoint and send the link. Outlook offers this natively, it is what
corporate IT expects, and it sidesteps attachment policy entirely.

---

## Showing the backend, if a judge asks

The web consoles are one view of the system. If somebody wants to see the API
itself — every route, the RBAC in action, the raw JSON — there are three ways,
in ascending order of how much internet they need.

### 1. The API console — works with no internet at all

```bash
./run.sh
open http://localhost:8090/api-console      # macOS
# xdg-open http://localhost:8090/api-console   # Linux
# start   http://localhost:8090/api-console    # Windows
```

Every operation the API exposes, the role each one needs, and a **Send** button
per route. Pick a role from the dropdown and re-send the same request to watch
the authorisation change. Served by the Python process itself — **no CDN, no
webfont, no outbound request of any kind**, so it renders on an air-gapped
network and on venue wifi that does not work.

### 2. FastAPI's own docs — richer, but needs internet

```bash
open http://localhost:8090/docs             # Swagger UI, try-it-out per route
open http://localhost:8090/redoc            # reference-style rendering
curl -s http://localhost:8090/openapi.json | python3 -m json.tool | head -40
```

Be aware before demonstrating these: `/docs` loads Swagger UI from
`cdn.jsdelivr.net` and `/redoc` also pulls Google Fonts. With no route out
they render as a **blank page**. `/api-console` above exists for exactly that
reason.

### 3. Straight from the terminal — the most convincing option

Nothing to install, and it is the same API the console calls. **The role
headers are the whole demonstration**: the same URL returns 200 or 403
depending on who is asking, and it is enforced in the API rather than by
hiding a button.

```bash
# Public — no role needed. Tonight's run: stage timings and counts, no identities.
curl -s http://localhost:8090/api/run | python3 -m json.tool

# Health: config version, live gate thresholds, ledger state.
curl -s http://localhost:8090/api/health | python3 -m json.tool

# WELFARE OFFICER — the escalated caseload for their own units.
curl -s -H 'X-Role: welfare_officer' -H 'X-Operator: wo-01' -H 'X-Units: UNIT-01' \
  http://localhost:8090/api/caseload | python3 -m json.tool

# AUDITOR — every refusal, nearest-miss first. This is the interesting one.
curl -s -H 'X-Role: auditor' -H 'X-Operator: aud-01' -H 'X-Units: ' \
  http://localhost:8090/api/refused | python3 -m json.tool | head -60

# The same URL as a welfare officer -> 403. Handing an officer a
# nearly-flagged list would lower the threshold to zero.
curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
  -H 'X-Role: welfare_officer' -H 'X-Operator: wo-01' -H 'X-Units: UNIT-01' \
  http://localhost:8090/api/refused

# COMMANDER — aggregates only, k>=5, suppressed rather than rounded.
curl -s -H 'X-Role: commander' -H 'X-Operator: co-01' -H 'X-Units: UNIT-01' \
  http://localhost:8090/api/unit/UNIT-01/heatmap | python3 -m json.tool

# ...and another unit they are not scoped to -> 403, in the software.
curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
  -H 'X-Role: commander' -H 'X-Operator: co-01' -H 'X-Units: UNIT-01' \
  http://localhost:8090/api/unit/UNIT-02/heatmap

# No role at all -> 401. Not 403: the API distinguishes "who are you" from
# "I know who you are, and no".
curl -s -o /dev/null -w 'HTTP %{http_code}\n' http://localhost:8090/api/caseload

# AUDITOR — the hash-chained ledger and the differential-privacy budget.
curl -s -H 'X-Role: auditor' -H 'X-Operator: aud-01' -H 'X-Units: ' \
  http://localhost:8090/api/audit | python3 -m json.tool | head -40
```

Expected results, so a wrong one is obvious:

| Request | Expect |
|---|---|
| `/api/run`, no headers | `200` — public, counts only |
| `/api/caseload` as `welfare_officer` | `200`, a short list |
| `/api/refused` as `auditor` | `200`, 125 refusals |
| `/api/refused` as `welfare_officer` | **`403`** |
| `/api/unit/UNIT-02/heatmap` scoped to `UNIT-01` | **`403`** |
| Any route with no `X-Role` | **`401`**, not 403 — the two are different on purpose: 401 is "who are you", 403 is "I know who you are and no" |

### If a judge asks to see a decision, not a route

```bash
uv run samvedna case pid-mon-0001    # the refused case, with the arithmetic
uv run samvedna cohorts              # all three fixture cohorts through the real engine
```

`pid-mon-0001` fails consistency at **0.694** against a **0.700** threshold. A
hardcoded demo does not fail by 0.006.

---

## Running this on another device

This is the whole procedure. Nothing else is needed: no network at build time
beyond the two package registries, no database, no credential, no GPU, no
account, and no file from any other project.

### 1. Get the tree onto the machine

Either unzip the archive from `tools/package.py`, or copy the folder off a
pendrive. Both are the same thing — the tree has no absolute paths in it.

```bash
unzip samvedna-*.zip && cd samvedna     # or: cp -R /Volumes/PENDRIVE/samvedna ~/ && cd ~/samvedna
```

### 2. Check what the machine already has

```bash
python3 --version     # need 3.11 or newer
node --version        # need 18 or newer
uv --version          # if missing: curl -LsSf https://astral.sh/uv/install.sh | sh
```

On Windows, use PowerShell and `irm https://astral.sh/uv/install.ps1 | iex`;
`run.sh` is bash, so use WSL, Git Bash, or the two manual commands in step 5.

### 3. Install

```bash
uv sync --all-extras          # Python side, resolved from the shipped uv.lock
cd web && npm install && cd ..  # console side, resolved from package-lock.json
```

Both lockfiles ship deliberately. Without them a fresh tree re-resolves
transitive dependencies to whatever is newest that day, and "it worked on the
other machine" stops being true.

### 4. Prove it before showing it

```bash
./check.sh
```

Lint, the full test suite, the L3 purity check, the portability check, and the
packaging check. If this is green the machine can run the demonstration. If the
Python tests pass but the console fails to build, it is almost always a stale
`node_modules` — delete it and re-run `npm install`.

### 5. Start it

```bash
./run.sh
```

It prints the URL. If port 3100 or 8090 is taken by something else on this
machine:

```bash
SAMVEDNA_WEB_PORT=4000 SAMVEDNA_API_PORT=8091 ./run.sh
```

Manually, if `run.sh` will not run (Windows without WSL):

```bash
uv run uvicorn samvedna.api.asgi:app --port 8090        # terminal 1
cd web && SAMVEDNA_API_PORT=8090 npm run dev -- -p 3100  # terminal 2
```

### 6. No browser at all?

The command line does everything the consoles do:

```bash
uv run samvedna run                 # a full nightly pipeline
uv run samvedna cohorts             # the three fixture cohorts through the gates
uv run samvedna case pid-mon-0001   # one case, arithmetic shown
```

### Troubleshooting, in the order things actually go wrong

| Symptom | Cause | Fix |
|---|---|---|
| Console renders unstyled, like raw HTML | `npm run build` ran while `npm run dev` was live; they share `.next` | `./run.sh --stop`, `rm -rf web/.next`, `./run.sh` |
| `Address already in use` | Another app holds the port | `./run.sh --status`, then set `SAMVEDNA_WEB_PORT` / `SAMVEDNA_API_PORT` |
| SSL / certificate errors from `uv` | Corporate TLS interception | `export SSL_CERT_FILE=$(python3 -c "import ssl;print(ssl.get_default_verify_paths().openssl_cafile)")` |
| Voice page shows no microphone | Browsers only allow mic on `localhost` or HTTPS | Use `localhost`, not a LAN IP |
| API answers, console shows nothing | API on a different port than the console expects | Set `SAMVEDNA_API_PORT` for **both** processes |
| `uv: command not found` after install | Installer put it in `~/.local/bin` | `export PATH="$HOME/.local/bin:$PATH"` |
| 12 tests skipped on a fresh copy | Trained model files are excluded from the archive as rebuildable — the pipeline does not need them, and the gates never did | Expected. `uv run --extra ml python tools/train_tabular.py` if you want them |

---

## Handing this to another agent

If you are opening this repository in Claude Code or a similar agent on a new
machine and want it productive immediately, paste the contents of
[`HANDOFF_PROMPT.md`](HANDOFF_PROMPT.md) as your first message. It states what
the system is, which invariants must not be broken, the four mistakes that were
actually made while building it, and where the work stands.

Read in this order:

1. [`HANDOFF_PROMPT.md`](HANDOFF_PROMPT.md) — the agent brief. Start here.
1. [`TRANSFER.md`](TRANSFER.md) — sending it, receiving it, merging a split
   transfer, and briefing an AI assistant on it.
2. [`docs/PS_COMPLIANCE.md`](docs/PS_COMPLIANCE.md) — every line of the
   problem statement against what is actually in the tree, with the limits
   stated rather than buried.
3. [`docs/TECH_STACK.md`](docs/TECH_STACK.md) — the declared stack vs. what
   runs and where, what happens when each part fails, and the tech-stack
   questions a judge will ask, answered.
4. [`docs/CONTEXT_PHASES.md`](docs/CONTEXT_PHASES.md) — every phase, what is
   done, what is open, and the evidence for each claim.
5. [`docs/SCALABILITY.md`](docs/SCALABILITY.md) — the measured numbers, and the
   one honest problem with them.
6. `src/samvedna/core/gates.py` — the product is in this one file.

---

## What this system will not do

- Let a model output reach a human without passing the gates
- Let any model, LLM or heuristic emit a gate value, a verdict or a confidence
- Put individual psychological data on a commanding officer's screen
- Hardcode a demo verdict — all three fixture cohorts run through the real engine
- Feed any output into ACR, posting, promotion or disciplinary processes
- Retrain or re-threshold itself without a recorded governance decision
- Suppress an acute self-disclosure because a persistence window is unsatisfied
- Report or surface that a person withdrew consent
- Send anything to an external cloud, analytics SDK or public LLM API

---

Build log with evidence for every phase: [`docs/PHASES.md`](docs/PHASES.md).
Reconciliation against PART 18 of the master prompt:
[`docs/RECONCILIATION.md`](docs/RECONCILIATION.md).
