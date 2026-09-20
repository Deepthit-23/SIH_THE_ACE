# Demo runbook — showing the local build to judges

All commands run from the repo root: `C:\Users\deept\Documents\MPLAD_SIH`
(open a terminal there, e.g. right-click the folder → "Open in Terminal", or in
VS Code: Terminal → New Terminal).

---

## 0 · Prerequisites (check once)

- **Docker Desktop** is installed and **running** (whale icon in the system tray,
  not spinning). Start it from the Start menu if needed and wait ~30 s.
- **Node.js** installed: `node -v` should print a version.
- The 4 source CSVs are in `data\raw\` (already there on this machine).

---

## 1 · Start the three services

You need **three terminals** (or three VS Code terminal tabs), one per service.
Leave all three running during the demo.

### Terminal 1 — backend + database (Docker)

```powershell
docker compose up -d
```

Wait ~15 s, then confirm it's healthy:

```powershell
curl http://localhost:8000/health
```
Expected: `{"status":"ok","database":"ok"}`

> The database keeps its data between runs. You only need to re-seed (section 4)
> if you ran `docker compose down -v` or are on a fresh clone.

### Terminal 2 — frontend

```powershell
cd frontend
npm install      # first time only, ~1 min
npm run dev
```
Leave it running. It serves the dashboard on **http://localhost:5173** and
forwards `/api/*` to the backend.

### Terminal 3 — public link (only if judges view it remotely)

```powershell
cloudflared tunnel --url http://localhost:5173
```
It prints a line like:
```
https://<random-words>.trycloudflare.com
```
**That URL is your shareable demo link.** Copy it. It changes every time you
restart the tunnel.

> If `cloudflared` is not found: `npm install -g cloudflared` (one time), then
> retry.

**If you're presenting on your own laptop with a projector, skip Terminal 3** —
just open http://localhost:5173 directly.

---

## 2 · Verify before you present (30 seconds)

```powershell
curl http://localhost:8000/health
curl "http://localhost:8000/risk-scores?limit=1"
curl http://localhost:8000/audit/verify
```

Expected: health ok · a project JSON with `"total": 131700` · `"valid": true`.

Then open the dashboard in a browser and check:
- the **national header strip** shows figures (Allocated ₹11,682 Cr … )
- the **"Audit trail verified ✓"** chip (green) is in the top-right
- the ranked list is populated

---

## 3 · The demo walkthrough (~4 minutes)

Open http://localhost:5173 (or the tunnel URL).

| step | what to show | where |
|---|---|---|
| 1 | **Scale** — national header: ₹11,682 Cr allocated across 774 MPs, 131,916 works scored, 3,690 high-risk | Risk list, top strip |
| 2 | **Ranked list** — every project scored 0–100, sorted; score bars shrink down the page. Filter by state / category, or **search** an MP name | Risk list |
| 3 | **A clean catch** — open **project 131836** (cost inflation, score 95). Show the plain-language reasons, split into *rule findings* and *anomaly-model signal*. The full six-type + four-role walkthrough is in `data/processed/demo_anchors.md` | `/projects/131836` |
| 4 | **Explainability** — the **"How the score is built"** bar: which rule contributed how much, plus the model | same page, scroll down |
| 5 | **The systemic case** — open **project 60625**: one vendor holds 64% of an MP's transactions + a 30× cost overrun | `/projects/60625` |
| 6 | **Auditor workflow** — on that project, set the case to **Under review**, then **Dismissed** with a reason. Note it appears in the **Review history**, and the reason is logged | Case status panel (right) |
| 7 | **Case log** — the "Case log" tab: every decision an auditor made, dismissal reasons visible — *"this is the feedback a production system would use to retune"* | `/cases` |
| 8 | **Patterns** — the "District / contractor patterns" tab: bar charts of where risk concentrates (BALRAMPUR, SHRAWASTI dominate) | `/patterns` |
| 9 | **Tamper-evidence** — see section 3a below | terminal + browser |
| 10 | **Offline handoff** — click **Export CSV** on the risk list; auditors get a spreadsheet | Risk list |

### 3a · The audit tamper demo (the "cybersecurity" beat)

In a spare terminal:

```powershell
# 1. show the chain is intact
curl http://localhost:8000/audit/verify
#    -> {"valid":true,"entries_checked":131700+,"broken_at":null}

# 2. tamper: rewrite a stored risk score directly in the database
docker compose exec db psql -U mplad -d mplad -c "UPDATE audit_log SET payload = jsonb_set(payload,'{combined_risk_score}','\"999.0000\"') WHERE id = 500;"

# 3. verify again — it pinpoints the tampered entry
curl http://localhost:8000/audit/verify
#    -> {"valid":false,"entries_checked":499,"broken_at":500}
```

Reload the dashboard — the header chip turns **red: "Audit trail tampered —
broken at #500"**.

**Undo it** (so the demo is clean for the next judge):

```powershell
docker compose exec backend python -m app.pipeline.score_projects
```
This re-scores and re-chains. `curl http://localhost:8000/audit/verify` is
`valid` again.

---

## 4 · Re-seed the database (only if empty / fresh clone / after `down -v`)

Run **in order** (Terminal 1 must have the stack up). Takes ~3–4 minutes.

```powershell
docker compose exec backend python -m app.pipeline.prepare_data --reset
docker compose exec backend python -m app.pipeline.inject_anomalies --clear
docker compose exec backend python -m app.pipeline.score_projects
```

Optional — regenerate the validation reports and demo anchor list:

```powershell
docker compose exec backend python -m app.pipeline.sanity_report
docker compose exec backend python -m app.pipeline.evaluate_rules
docker compose exec backend python -m app.pipeline.evaluate_ml
docker compose exec backend python -m app.pipeline.demo_anchors
docker compose exec backend python -m pytest        # 118 tests
```

> `demo_anchors` writes `data/processed/demo_anchors.md`: one project per anomaly type plus a
> Ministry / State / District / MP walkthrough, with the HTTP access each demo account actually gets.
> Synthetic project IDs shift whenever `inject_anomalies` re-runs, so regenerate it after any
> re-inject or re-score and use the IDs it prints (real projects such as **60625**, **10360**, **176**
> keep their IDs).

---

## 5 · Troubleshooting

| symptom | fix |
|---|---|
| `docker compose` errors / `Cannot connect to the Docker daemon` | Docker Desktop isn't running — start it, wait 30 s |
| `curl http://localhost:8000/health` fails | `docker compose logs backend --tail 30` ; if DB-related, `docker compose restart backend` |
| Port 5173 "in use" | a stuck node process: `Get-Process node \| Stop-Process -Force`, then `npm run dev` again |
| Dashboard loads but no data | backend not up, or DB not seeded → section 4 |
| Audit chip missing (not red, just absent) | transient fetch error — reload the page |
| Tunnel URL stopped working | `cloudflared` was killed or the laptop slept — re-run Terminal 3, share the new URL |
| `cloudflared: command not found` | `npm install -g cloudflared` |

---

## 6 · Shut down after the demo

```powershell
# Ctrl+C in Terminal 2 (vite) and Terminal 3 (cloudflared)
docker compose stop           # keeps the data; `docker compose up -d` next time
# or: docker compose down      # removes containers, keeps the data volume
# never: docker compose down -v  (that wipes the seeded database)
```
