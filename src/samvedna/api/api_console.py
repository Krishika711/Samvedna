"""A self-contained API console. No CDN, no webfont, no outbound request.

FastAPI ships `/docs` and `/redoc` and they are genuinely useful — but they
pull Swagger UI from `cdn.jsdelivr.net`, a favicon from `fastapi.tiangolo.com`
and two families from Google Fonts. In an air-gapped force data centre all
three fail and `/docs` renders as a blank page; on a network that *does* have a
route out, they announce to three third parties that this data centre runs this
system, on every page load. That is the same objection this project already
documents for webfonts, and it applies with more force to a page whose whole
purpose is proving the backend is real.

It is also the page most likely to be opened on a venue wifi that does not
work.

So this is a second console that owes nothing to anybody: one HTML string, one
inline stylesheet, one inline script, built from the app's own OpenAPI schema
at request time. `/docs` is left mounted for anybody who has internet and
prefers it.

It does one thing Swagger UI cannot, which is why it is not merely a
replacement: **it knows the RBAC headers.** Every route here carries the role
that may call it, so a judge can switch role and watch the same request return
200 and then 403 — which is the demonstration, not a footnote to it.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

__all__ = ["attach"]

# Which role each route family expects. Derived from the grant table in
# `disclosure/rbac.py` rather than guessed — kept here as a display hint only;
# the API still enforces its own rules and this table cannot grant anything.
ROLE_HINTS: tuple[tuple[str, str, str], ...] = (
    ("/api/caseload", "welfare_officer", "Escalated cases for the officer's units"),
    ("/api/case/", "welfare_officer", "One case; disclose/contact/close/defer/contest"),
    ("/api/refused", "auditor", "Every refusal — 403 for a welfare officer, on purpose"),
    ("/api/audit", "auditor", "Hash-chained ledger and the DP budget"),
    ("/api/unit/", "commander", "Aggregates only, k≥5, suppressed not rounded"),
    ("/api/me/", "personnel", "A person's own drivers and gate arithmetic"),
    ("/api/consent", "personnel", "Record or withdraw consent"),
    ("/api/voice/", "personnel", "Live voice sitting — add-on"),
    ("/api/locales", "", "Public: the eight consent locales"),
    ("/api/run", "", "Public: tonight's run. Counts only, no identities"),
    ("/api/health", "", "Public: config version, thresholds, ledger state"),
)

_PRESETS = {
    "welfare_officer": ("wo-01", "UNIT-01"),
    "commander": ("co-01", "UNIT-01"),
    "auditor": ("aud-01", ""),
    "personnel": ("self", ""),
    "": ("", ""),
}


def _hint_for(path: str) -> tuple[str, str]:
    """Longest-prefix match, so `/api/case/{pid}` beats a bare `/api/`."""
    best = ("", "")
    best_len = -1
    for prefix, role, note in ROLE_HINTS:
        if path.startswith(prefix) and len(prefix) > best_len:
            best, best_len = (role, note), len(prefix)
    return best


def attach(app: FastAPI) -> None:
    @app.get("/api-console", response_class=HTMLResponse, include_in_schema=False)
    def api_console(request: Request) -> HTMLResponse:
        schema = request.app.openapi()
        rows = []
        for path, methods in sorted(schema.get("paths", {}).items()):
            for method, spec in methods.items():
                if method.upper() not in ("GET", "POST"):
                    continue
                role, note = _hint_for(path)
                operator, units = _PRESETS.get(role, ("", ""))
                rows.append(
                    {
                        "method": method.upper(),
                        "path": path,
                        "summary": (spec.get("summary") or "").strip(),
                        "role": role,
                        "operator": operator,
                        "units": units,
                        "note": note,
                    }
                )
        return HTMLResponse(_page(schema, rows))


def _page(schema: dict, rows: list[dict]) -> str:
    import json

    info = schema.get("info", {})
    public = sum(1 for r in rows if not r["role"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SAMVEDNA API console</title>
<style>
  /* Four brand tokens, same as the web console, so the two look like one
     product. System fonts only — see the module docstring. */
  :root {{
    --deep:#16243D; --mid:#24406E; --accent:#E0571C; --tint:#F0F3F7;
    --card:#fff; --rule:#C9D3E0; --rule-soft:#DFE6EF;
    --ink:#14203A; --ink-2:#46556F; --ink-3:#74819A;
    --pass:#14724A; --pass-soft:#DEF0E7;
    --hold:#A9670A; --hold-soft:#FBEDD6;
    --stop:#B3271C; --stop-soft:#FBE4E1;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --tint:#0D1420; --card:#151E2C; --rule:#2A3646; --rule-soft:#202B3A;
      --ink:#E6EBF2; --ink-2:#A5B1C2; --ink-3:#77839A; --mid:#7FA1D9;
      --accent:#FF7A3D;
      --pass:#5FB68F; --pass-soft:#13291F;
      --hold:#DFA455; --hold-soft:#2A2113;
      --stop:#E0827A; --stop-soft:#2B1715;
    }}
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--tint);color:var(--ink);font:15px/1.5 var(--sans)}}
  header{{background:var(--deep);color:#EDF2F9;padding:22px 28px}}
  header h1{{margin:0;font-size:1.35rem;letter-spacing:-.01em}}
  header p{{margin:5px 0 0;color:#A9BAD4;font-size:.88rem}}
  .wrap{{max-width:1120px;margin:0 auto;padding:20px 28px 60px}}
  .bar{{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;
        background:var(--card);border:1px solid var(--rule);border-radius:4px;
        padding:14px 16px;margin:18px 0}}
  .f{{display:flex;flex-direction:column;gap:4px}}
  label{{font:600 .66rem/1 var(--mono);letter-spacing:.09em;
         text-transform:uppercase;color:var(--ink-3)}}
  select,input{{font:14px var(--mono);padding:7px 9px;border:1px solid var(--rule);
                border-radius:3px;background:var(--card);color:var(--ink);min-width:150px}}
  .note{{font-size:.82rem;color:var(--ink-3);flex:1;min-width:220px}}
  table{{width:100%;border-collapse:collapse;background:var(--card);
         border:1px solid var(--rule);border-radius:4px;overflow:hidden}}
  th{{text-align:left;font:600 .64rem/1 var(--mono);letter-spacing:.1em;
      text-transform:uppercase;color:var(--ink-3);padding:10px 12px;
      background:var(--tint);border-bottom:1px solid var(--rule)}}
  td{{padding:9px 12px;border-bottom:1px solid var(--rule-soft);
      vertical-align:top;font-size:.86rem}}
  tr:last-child td{{border-bottom:none}}
  .m{{font:600 .68rem/1 var(--mono);padding:3px 7px;border-radius:2px}}
  .m-GET{{background:var(--pass-soft);color:var(--pass)}}
  .m-POST{{background:var(--hold-soft);color:var(--hold)}}
  code{{font:.82rem var(--mono);color:var(--ink)}}
  .role{{font:.7rem var(--mono);letter-spacing:.04em;color:var(--ink-2)}}
  .role.pub{{color:var(--pass)}}
  button{{font:600 .8rem var(--sans);padding:6px 13px;border-radius:3px;cursor:pointer;
          background:var(--accent);color:#fff;border:1px solid var(--accent)}}
  button.ghost{{background:transparent;color:var(--mid);border-color:var(--rule)}}
  button:disabled{{opacity:.5;cursor:default}}
  .out{{margin-top:8px;background:#0E1828;color:#DCE8F7;border-radius:3px;
        padding:10px 12px;font:.76rem/1.45 var(--mono);white-space:pre-wrap;
        max-height:260px;overflow:auto}}
  .st{{font:600 .68rem var(--mono);padding:2px 7px;border-radius:2px;margin-inline-end:8px}}
  .ok{{background:var(--pass-soft);color:var(--pass)}}
  .no{{background:var(--stop-soft);color:var(--stop)}}
  .pathcell{{min-width:210px}}
</style></head><body>
<header>
  <h1>SAMVEDNA — API console</h1>
  <p>{info.get("title", "")} {info.get("version", "")} ·
     {len(rows)} operations, {public} public ·
     served by this process, with no external asset of any kind</p>
</header>
<div class="wrap">
  <div class="bar">
    <div class="f">
      <label for="role">X-Role</label>
      <select id="role">
        <option value="">(none — public routes only)</option>
        <option value="welfare_officer">welfare_officer</option>
        <option value="commander">commander</option>
        <option value="auditor">auditor</option>
        <option value="personnel">personnel</option>
        <option value="mental_health_authority">mental_health_authority</option>
      </select>
    </div>
    <div class="f"><label for="operator">X-Operator</label><input id="operator" value=""></div>
    <div class="f"><label for="units">X-Units</label><input id="units" value=""></div>
    <p class="note">
      Change the role and re-send the same request. A welfare officer calling
      <code>/api/refused</code> gets <strong>403</strong> — handing an officer a
      nearly-flagged list would lower the threshold to zero. That is the
      demonstration.
    </p>
  </div>

  <table>
    <thead><tr>
      <th style="width:62px">Method</th><th class="pathcell">Path</th>
      <th style="width:130px">Needs role</th><th>What it returns</th>
      <th style="width:88px">Try</th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table>

  <p class="note" style="margin-top:16px">
    FastAPI's own <code>/docs</code> and <code>/redoc</code> are still mounted
    and are richer than this page — but they load Swagger UI from
    <code>cdn.jsdelivr.net</code> and fonts from Google, so they render blank
    without internet. This page has no such dependency.
  </p>
</div>
<script>
const ROWS = {json.dumps(rows)};
const PRESETS = {json.dumps(_PRESETS)};
const $ = (id) => document.getElementById(id);

$("role").addEventListener("change", () => {{
  const p = PRESETS[$("role").value] || ["", ""];
  $("operator").value = p[0];
  $("units").value = p[1];
}});

function headers() {{
  const h = {{}};
  if ($("role").value) h["X-Role"] = $("role").value;
  if ($("operator").value) h["X-Operator"] = $("operator").value;
  h["X-Units"] = $("units").value;
  return h;
}}

/* A path with a {{pid}} in it needs a real one. Rather than making the judge
   find one, the first escalated case from /api/caseload is offered — and when
   that is empty (which it will be for a role that cannot see cases) the
   published fixture pid is used, because it is the refused case and therefore
   the interesting one. */
let sampled = null;
async function samplePid() {{
  if (sampled) return sampled;
  try {{
    const r = await fetch("/api/caseload", {{ headers: {{
      "X-Role": "welfare_officer", "X-Operator": "wo-01", "X-Units": "UNIT-01",
    }} }});
    const b = await r.json();
    sampled = b?.cases?.[0]?.pid || "pid-mon-0001";
  }} catch {{ sampled = "pid-mon-0001"; }}
  return sampled;
}}

async function send(row, cell) {{
  const out = cell.querySelector(".out") || document.createElement("div");
  out.className = "out";
  out.textContent = "sending…";
  if (!out.parentNode) cell.appendChild(out);

  let path = row.path;
  if (path.includes("{{")) {{
    const pid = await samplePid();
    path = path.replace(/\\{{pid\\}}/g, pid)
               .replace(/\\{{unit_id\\}}/g, $("units").value || "UNIT-01")
               .replace(/\\{{session_id\\}}/g, "none");
  }}

  try {{
    const res = await fetch(path, {{
      method: row.method,
      headers: row.method === "POST"
        ? {{ ...headers(), "Content-Type": "application/json" }}
        : headers(),
      body: row.method === "POST" ? "{{}}" : undefined,
    }});
    const text = await res.text();
    let body = text;
    try {{ body = JSON.stringify(JSON.parse(text), null, 2); }} catch {{}}
    const cls = res.ok ? "ok" : "no";
    out.innerHTML = "";
    const badge = document.createElement("span");
    badge.className = "st " + cls;
    badge.textContent = res.status + " " + res.statusText;
    out.appendChild(badge);
    out.appendChild(document.createTextNode(
      "  " + path + "\\n\\n" + body.slice(0, 4000)
    ));
  }} catch (e) {{
    out.textContent = "network error: " + e.message;
  }}
}}

const tbody = $("rows");
for (const row of ROWS) {{
  const tr = document.createElement("tr");

  const m = document.createElement("td");
  const badge = document.createElement("span");
  badge.className = "m m-" + row.method;
  badge.textContent = row.method;
  m.appendChild(badge);

  const p = document.createElement("td");
  p.className = "pathcell";
  const c = document.createElement("code");
  c.textContent = row.path;
  p.appendChild(c);

  const r = document.createElement("td");
  const rs = document.createElement("span");
  rs.className = "role" + (row.role ? "" : " pub");
  rs.textContent = row.role || "public";
  r.appendChild(rs);

  const d = document.createElement("td");
  d.textContent = row.note || row.summary || "—";

  const t = document.createElement("td");
  const b = document.createElement("button");
  b.textContent = "Send";
  b.addEventListener("click", () => send(row, d));
  t.appendChild(b);

  tr.append(m, p, r, d, t);
  tbody.appendChild(tr);
}}
</script>
</body></html>"""
