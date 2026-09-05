# MPLAD Anomaly & Fraud Detection

Prototype for **SIH26102 — AI-Based Anomaly & Fraud Detection in the MPLAD Scheme**
(Ministry of Statistics & Programme Implementation).

Ingests MPLAD project expenditure data and flags suspicious entries using a
**rule engine** plus an **Isolation Forest** model. Every flagged project comes
with a plain-language explanation of *why* it was flagged. Output is a ranked
dashboard for auditors plus a district / contractor pattern view.

## Stack

| Layer     | Tech                                                    |
| --------- | ------------------------------------------------------- |
| Backend   | Python, FastAPI, SQLAlchemy, PostgreSQL                 |
| ML        | scikit-learn (IsolationForest), SHAP                    |
| Frontend  | React (Vite), Tailwind CSS, Recharts                    |
| Local dev | Docker Compose (Postgres + backend)                     |

## Repo layout

```
backend/     FastAPI app (app/), Dockerfile, requirements
frontend/    Vite + React + Tailwind dashboard
data/        data prep scripts + raw/processed CSVs (Phase 2)
docker-compose.yml
```

## Running locally

### 1. Backend + database (Docker)

```bash
docker compose up --build
```

- API:  http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health
- Postgres: localhost:5432 (`mplad` / `mplad`, db `mplad`)

Tables are created automatically on backend startup.

### 2. Frontend (local Node)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api/*` to the backend on
:8000.

## Status

- [x] **Phase 1** — scaffold, schema, runnable skeleton
- [ ] Phase 2 — data pipeline + synthetic anomalies
- [ ] Phase 3 — rule engine
- [ ] Phase 4 — Isolation Forest + explainability
- [ ] Phase 5 — dashboard
- [ ] Phase 6 — audit hash-chain
- [ ] Phase 7 — integration & polish

## Scope notes

This is a 5-day hackathon prototype. Deliberately **out of scope**: real
blockchain/DLT (a simple hash-chained audit table stands in), production auth /
security hardening, live scraping pipelines, MLOps / retraining, deep mobile
responsiveness.

Synthetic anomalies are injected into the dataset for precision/recall
validation and are labelled **internally only** — never exposed via the API or
UI.
