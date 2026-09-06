# MPLAD Anomaly & Fraud Detection

Prototype for **SIH26102 — AI-Based Anomaly & Fraud Detection in the MPLAD Scheme**
(Ministry of Statistics & Programme Implementation).

Ingests MPLAD project data, flags suspicious entries with a **rule engine** + an
**Isolation Forest** model, and gives every flagged project a plain-language
explanation of *why*. Output: a ranked risk dashboard for auditors, a
district/contractor pattern view for systemic issues, and a tamper-evident audit
trail.

## Stack

| Layer     | Tech |
| --------- | ---- |
| Backend   | Python 3.11, FastAPI, SQLAlchemy, PostgreSQL 16 |
| ML        | scikit-learn (IsolationForest); explainability = feature-deviation ranking |
| Frontend  | React 18 (Vite), Tailwind CSS, Recharts |
| Local dev | Docker Compose (Postgres + backend); frontend runs on local Node |

## Prerequisites

- Docker + Docker Compose v2
- Node 18+ and npm (for the frontend dev server)
- The four MPLAD source CSVs in `data/raw/` (git-ignored — not committed):
  `mplads_recommended_works_*.csv`, `mplads_completed_works_*.csv`,
  `mplads_expenditures_*.csv`, `mplads_mp_summary_*.csv`

## Quick start (cold clone → working app)

```bash
git clone https://github.com/Deepthit-23/SIH_THE_ACE.git
cd SIH_THE_ACE

# 0. put the four source CSVs in data/raw/  (see Prerequisites)

# 1. backend + database
docker compose up -d --build          # ~3-4 min first build
curl -sf http://localhost:8000/health # wait for {"status":"ok","database":"ok"}

# 2. build the data + scores  (each step is idempotent; run in this order)
docker compose exec backend python -m app.pipeline.prepare_data --reset      # load CSVs  (~30s)
docker compose exec backend python -m app.pipeline.inject_anomalies --clear  # synthetic anomalies
docker compose exec backend python -m app.pipeline.score_projects            # rules + ML -> risk_flags + audit chain

# 3. frontend
cd frontend
npm install
npm run dev                           # http://localhost:5173
```

Open **http://localhost:5173**. API docs at **http://localhost:8000/docs**.

Nothing else is required — no migrations, no manual DB setup, no env files.
Postgres tables are created on backend startup; `prepare_data --reset` drops and
recreates the data tables.

### Reset everything

```bash
docker compose down -v && docker compose up -d --build   # wipes the DB volume
# then re-run step 2
```

### Optional — validation reports & tests

```bash
docker compose exec backend python -m pytest                       # 35 tests
docker compose exec backend python -m app.pipeline.sanity_report   # -> data/processed/sanity_report.md
docker compose exec backend python -m app.pipeline.evaluate_rules  # -> data/processed/rule_eval.md
docker compose exec backend python -m app.pipeline.evaluate_ml     # -> data/processed/ml_eval.md
```

## Repo layout

```
backend/
  app/
    main.py              FastAPI app
    models.py schemas.py database.py config.py
    routers/            health, meta, projects, risk, patterns, audit
    audit.py            SHA-256 hash-chain (build / verify)
    pipeline/
      prepare_data.py   CSV -> Postgres
      inject_anomalies.py  synthetic fraud patterns (internal labels only)
      categorize.py ida.py features.py   shared transforms
      rules.py          4-rule engine (pure, tested)
      ml_model.py       IsolationForest + feature-deviation explainability
      risk_scorer.py    combines rule + ML -> combined_risk_score + explanation
      score_projects.py end-to-end: writes risk_flags + audit_log
      evaluate_rules.py evaluate_ml.py sanity_report.py
  tests/                35 unit + integration tests
frontend/
  src/  pages/ components/ hooks/ lib/ api/
data/
  raw/                  source CSVs (git-ignored)
  processed/            generated reports (git-ignored)
docker-compose.yml
```

## API

Verify at http://localhost:8000/docs.

| endpoint | purpose |
|---|---|
| `GET /risk-scores` | ranked list — paginated, sortable (risk/amount), filterable (min_score, derived_category, state, district, status) |
| `GET /projects/{id}` | full project + ordered explanation list (rule + ML reasons) |
| `GET /patterns/districts`, `GET /patterns/contractors` | cross-entity rankings for the pattern charts |
| `GET /districts/{d}/pattern`, `GET /contractors/{v}/pattern` | single-entity drill-in |
| `GET /meta/filters` | filter option lists + score-band counts |
| `GET /audit/verify` | walk the hash-chain → `{valid, entries_checked, broken_at}` |

## How scoring works

1. **Rule engine** (`rules.py`) — 4 independent rules, each returns a boolean + a
   plain-language reason: cost anomaly (z-score vs `derived_category`+district
   peers), contractor concentration (one vendor's share of an MP's transactions),
   stalled/ghost project (old recommendation + no completion/payment activity +
   low-delivery MP), payment gap (in-progress payment share vs MP utilisation).
2. **Isolation Forest** (`ml_model.py`) — unsupervised, trained on 28 engineered
   features. The synthetic-anomaly labels are **never** a model input (evaluation
   only). Explanation = top feature deviations from the population, in plain
   language.
3. **Combiner** (`risk_scorer.py`) — rule points (cost 40, contractor 30, payment
   25, stalled 15) + a smooth-knee ML contribution + a cost-z tie-breaker →
   one `combined_risk_score` (0–100) and a single ordered explanation list.
   Bands: **≥ 70 high · 50–69 medium · < 50 low**.
4. **Audit chain** (`audit.py`) — every `score_projects` run appends one
   SHA-256-chained `audit_log` entry per project:
   `this_hash = sha256(canonical_payload + previous_hash)` (genesis = 64 zeros).
   Altering any past entry breaks every hash after it; `GET /audit/verify`
   detects it and reports `broken_at`. The dashboard header shows a live
   "Audit trail verified ✓" chip.

## Validation (synthetic anomalies)

Real MPLAD fraud isn't labelled, so `inject_anomalies` appends ~400 synthetic
project rows + ~1,800 synthetic vendor transactions with realistic-but-extreme
patterns, tagged `is_synthetic_anomaly` / `anomaly_type` **internally only** —
never exposed via API or UI. Scoring is deterministic (fixed seed, `ORDER BY id`
loads). Latest run (`data/processed/rule_eval.md` / `ml_eval.md`):

| anomaly type | rule recall | + ML (combined) | FP (real) |
|---|--:|--:|--:|
| cost_inflation | 80.8% | 86.8% | cost rule 2.2% |
| stalled_project | 66.7% | 68.0% | stalled rule 8.5% |
| contractor_concentration | 100% (8/8 MP units) | 100% | 0.6% of groups |
| payment_gap | 100% (6/6 MP units) | 100% | 2.9% of groups |

Combined `score ≥ 70` flags **2.2%** of real projects; ML adds **17** synthetic
anomalies the rules missed (15 cost, 2 stalled).

## Demo anchor projects

Navigate straight to `/projects/<id>`. Regenerate with
`docker compose exec backend python -m app.pipeline.demo_anchors`
(→ `data/processed/demo_anchors.md`) after any pipeline re-run.

| # | id | what it shows | score |
|---|---|---|--:|
| 1 | **131836** | clean **cost inflation** catch — cost rule is the sole driving signal (8.8× the road-paving average for Madurai) + ML "absolute amount is very large" | 93 |
| 2 | **60625** | **contractor concentration** — one vendor holds 64% of an MP's transactions in Allahabad, alongside a 30× cost overrun | 96 |
| 3 | **131951** | **stalled / ghost project** — the deliberately weak signal: recommended 32 months ago, no completion or payment activity, sits at a low score | 15 |
| 4 | **4708** | **mid-tier combined** — cost rule (4.8×) + ML agreeing, neither conclusive alone, lands in the medium band | 70 |

_(synthetic project ids shift if `inject_anomalies` is re-run; ids 60625 and 4708 are real projects and stable.)_

## Deployment

- **Local (primary):** the Docker Compose path above. Fully self-contained, no
  internet needed after the first image build.
- **Hosted:** frontend on Vercel, backend + Postgres on Render/Railway. See
  `DEPLOY.md`.

## Out of scope — deliberate

This is a prototype. The following were **intentionally not built**, to keep the
scope honest:

- **No real blockchain / distributed ledger.** The `audit_log` hash-chain is a
  single-writer demonstration of tamper-evidence — no consensus, no replication.
- **No authentication / authorization / security hardening.** Anyone who can
  reach the API can read everything. Not production-ready.
- **No live scraping.** Data is loaded from static CSV exports.
- **No MLOps / model retraining pipeline.** The model is retrained in-process on
  each `score_projects` run with a fixed seed.
- **No deep mobile responsiveness.** Designed for a desktop auditor workflow.

Flags are decision-support for auditors, **not** findings of wrongdoing.
