# Deployment

Two paths. **Local Docker is the primary path** — fully offline once built.
The hosted deploy is an optional shareable link.

---

## A. Local (primary — no internet needed after first build)

```bash
docker compose up -d --build
docker compose exec backend python -m app.pipeline.prepare_data --reset
docker compose exec backend python -m app.pipeline.inject_anomalies --clear
docker compose exec backend python -m app.pipeline.score_projects
cd frontend && npm install && npm run dev
```

→ http://localhost:5173 . See the main `README.md`.

---

## B. Hosted fallback — Vercel (frontend) + Render (backend + Postgres)

### 1. Postgres + backend on Render

1. **New → PostgreSQL** (free tier). Copy the *Internal Database URL*.
2. **New → Web Service**, connect the repo, root directory `backend/`.
   - Environment: **Docker** (uses `backend/Dockerfile`).
   - Health check path: `/health`.
   - Env vars:
     | key | value |
     |---|---|
     | `DATABASE_URL` | the Internal Database URL, with `postgresql://` → `postgresql+psycopg2://` |
     | `DATA_DIR` | `/data` |
     | `CORS_ORIGINS` | `https://<your-vercel-app>.vercel.app` (comma-sep for multiple) |
3. First deploy will start the API with empty tables. Seed it once from the
   Render **Shell**:
   ```bash
   # upload the 4 CSVs to /data/raw first (Render Disk, or commit a small sample)
   python -m app.pipeline.prepare_data --reset
   python -m app.pipeline.inject_anomalies --clear
   python -m app.pipeline.score_projects
   ```
   > Render's free tier has an ephemeral filesystem and the service sleeps after
   > inactivity — fine for a demo, but re-seed if the DB resets. For a stable
   > demo, attach a small **Render Disk** at `/data` and a paid Postgres, or use
   > Railway (persistent volume + no sleep on the trial).

### 2. Frontend on Vercel

1. **New Project**, import the repo, root directory `frontend/`.
2. Framework preset: **Vite**. Build `npm run build`, output `dist`.
3. Env var: `VITE_API_BASE = https://<your-render-service>.onrender.com`
4. Deploy. The app calls the Render backend directly (CORS is allow-listed via
   `CORS_ORIGINS` above).

### Railway alternative (backend + DB)

`railway init` → add a **PostgreSQL** plugin → deploy the repo with root
`backend/`, Docker builder. Set the same env vars. Railway gives `DATABASE_URL`
automatically (rewrite the scheme to `postgresql+psycopg2://`).

---

## Config the app reads

| var | default | used by |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://mplad:mplad@localhost:5432/mplad` | backend |
| `DATA_DIR` | `../data` (local) / `/data` (compose) | pipeline scripts |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | backend (comma-separated) |
| `VITE_API_BASE` | `/api` (dev proxy) | frontend build |

No secrets are committed. `.env.example` documents the local values; there is no
`.env` in the repo.
