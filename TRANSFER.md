# Transferring SAMVEDNA, and picking it up at the other end

Everything needed to move this project to another machine and have an AI
assistant continue the work without breaking it.

Three audiences, three sections. Read the one you are.

---

## 1. Sending it

Build the transfer files:

```bash
uv run python tools/package.py     # dist/samvedna-<date>.zip
uv run python tools/mailsafe.py    # dist/samvedna-<date>.zip.txt   <- attach this
```

**Attach the `.txt`, never the `.zip`.** Mail gateways block `.zip` outright —
not for what is inside it, but for being a zip. They also commonly block
`.py`, `.js`, `.mjs` and `.sh` *inside* archives, and this project is 116
Python files and three shell scripts. The `.txt` is the same archive as base64
with no zip header to recognise, no blocked extension, and nothing executable
to scan.

### If one file is refused

At ~4.2 MB the single file clears Outlook (10 MB) and Gmail (25 MB) but not a
strict 4 MB gateway. Split it:

```bash
uv run python tools/mailsafe.py --split 2
#   dist/samvedna-<date>.zip.part1of2.txt   (~2.1 MB)
#   dist/samvedna-<date>.zip.part2of2.txt   (~2.1 MB)
```

Send both, in either order, in one message or two. **Each part carries the
checksum of the whole archive and the full merge instructions**, so a
recipient holding both needs nothing else — and one missing a part finds out
before unzipping rather than after.

Use `--split 3` or more if the limit is tighter.

---

## 2. Receiving it

### One file

Open the `.txt`. The instructions are the first forty lines. In short:

```bash
awk '/^-----BEGIN SAMVEDNA ARCHIVE-----/{f=1;next} /^-----END SAMVEDNA ARCHIVE-----/{f=0} f' \
  samvedna-<date>.zip.txt | base64 -d > samvedna-<date>.zip
shasum -a 256 samvedna-<date>.zip     # must match the header
unzip samvedna-<date>.zip && cd samvedna
```

### Two files

Put both parts in one folder, then **one** command:

```bash
cat samvedna-<date>.zip.part*of2.txt |
  awk '/^-----BEGIN SAMVEDNA ARCHIVE-----/{f=1;next} /^-----END SAMVEDNA ARCHIVE-----/{f=0} f' |
  base64 -d > samvedna-<date>.zip
```

The `*` sorts correctly because the parts are numbered. Windows PowerShell
equivalents are in every part's header.

**Then check the merge before doing anything else:**

```bash
shasum -a 256 samvedna-<date>.zip          # macOS / Linux
certutil -hashfile samvedna-<date>.zip SHA256   # Windows
```

It must equal the `sha256 (whole)` line in the part headers. If it does not, a
part is missing, truncated, or out of order — **do not unzip it**. A wrong
merge can still produce an archive that unzips *partially*, which is worse
than one that fails outright, because it leaves somebody running half a
system that looks complete.

### Then

```bash
cd samvedna
uv sync --all-extras
(cd web && npm install)
./check.sh          # ~810 tests, lint, purity, portability, packaging
./run.sh            # prints the URL
```

`./check.sh` green means the machine can run the demonstration. Full
prerequisites and a troubleshooting table are in `README.md` under *Running
this on another device*.

---

## 3. Briefing an AI assistant on it

**Paste `HANDOFF_PROMPT.md` as your first message.** It is written for an agent
rather than a person and states the invariants, the bugs that were actually
made here, and the technology choices that look like mistakes and are not.

Then, in this order:

| Read | For |
|---|---|
| `HANDOFF_PROMPT.md` | The invariants. **Start here.** |
| `docs/CONTEXT_PHASES.md` | Every phase, what is done, what is **Open** |
| `docs/TECH_STACK.md` | Declared vs running stack, fallbacks, judge Q&A |
| `docs/PS_COMPLIANCE.md` | The problem statement, line by line |
| `src/samvedna/core/gates.py` | The product, in one short file |

### The shortest possible briefing

If you only give an assistant one paragraph, give it this:

> SAMVEDNA decides whether a welfare concern is strong enough to put a
> soldier's name in front of a human. **The product is the refusal, not the
> prediction.** A model produces a suspicion; four deterministic gates in
> `core/gates.py` decide whether it may become a name. No model, LLM or
> heuristic may ever emit a gate value, a verdict or a confidence. `core/` is
> pure and an AST test fails the build on I/O, a clock, `random` or `numpy`.
> Run `./check.sh` before and after every change; if a test fails, the test is
> almost certainly right.

### Things an assistant will get wrong unless told

- **Do not "upgrade" the substituted dependencies.** LightGBM, torch, Flower,
  Opacus and Flutter were all rejected for one reason: this project has to
  survive being copied onto a pendrive and emailed. `docs/TECH_STACK.md` has
  the table.
- **Do not weaken a gate to make a demo escalate.** A severe self-assessment
  correctly does not name most people. That is the thesis, not a bug.
- **Absent is not zero.** It cost two separate bugs. A domain with no data for
  a window is excluded from that window, not counted as zero.
- **Never put binary through a text operation.** `read_bytes().strip()`
  silently corrupted one encryption key in twenty-one.
- **`./check.sh` must be able to fail.** `set -o pipefail` does not cross a
  process boundary; inline blocks go through `block()`.

`tests/core/test_binary_discipline.py` and `tests/core/test_shell_discipline.py`
enforce the last two by walking the source, so an assistant that forgets is
told which file and line.

---

## What to do next

`docs/CONTEXT_PHASES.md` carries the full list with reasons. The short version:

| # | Next | Why it is open |
|--:|---|---|
| 1 | **Validation on real cohort data** | No real dataset exists. The training label is `strain >= 0.55` — circular. Needs ethics approval and a data-sharing agreement, not an afternoon. |
| 2 | **Persist the audit ledger** | State survives a restart; the ledger does not. Journal entries with original timestamps and hashes so the chain verifies across processes. ~1 hour, and the only known gap in the restart story. |
| 3 | **PHQ-9 licensing** | Real items and scoring are implemented. Validated translations cannot be invented. |
| 4 | **Threshold calibration** | The dial is exposed and the curve measured; the operating point is a command decision about welfare-cell capacity. |
| 5 | **TimescaleDB feature store** | Identity, ledger and consent are persisted and encrypted. The feature store is the volume that wants hypertable tuning. |
| 6 | **Deployment hardening** | Encryption at rest, key custody and erasure are built. Segmentation, OS hardening, key rotation and a pen test are deployment activities. |

---

## Verifying any of this

```bash
./check.sh                                  # everything
./check.sh --transfer                       # unzip into a temp dir, run cold
uv run python tools/mailsafe.py --split 2   # two-part transfer
uv run python tools/mailsafe.py --merge dist/*.part*of2.txt   # merge + verify
uv run python tools/export_dataset.py       # the cohort as CSV, for judges
uv run samvedna cohorts                     # the gates, no web layer
```
