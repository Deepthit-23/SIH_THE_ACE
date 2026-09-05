# Data

- `raw/` — original MPLAD exports (git-ignored, not committed). Four files,
  matched by glob so the date suffix doesn't matter:
  - `mplads_recommended_works_*.csv` (~87k) → `projects` (status=`recommended`)
  - `mplads_completed_works_*.csv` (~44k) → `projects` (status=`completed`)
  - `mplads_expenditures_*.csv` (~109k) → `vendor_transactions`
  - `mplads_mp_summary_*.csv` (774) → `mp_summary`
- `processed/` — `sanity_report.md` and other generated outputs (git-ignored).
- `prepare_data.py` — repo-root convenience shim → `app.pipeline.prepare_data`.

## Pipeline (run inside the backend container)

```bash
docker compose exec backend python -m app.pipeline.prepare_data --reset
docker compose exec backend python -m app.pipeline.inject_anomalies --clear
docker compose exec backend python -m app.pipeline.sanity_report
```

Implementation: `backend/app/pipeline/`
- `categorize.py` — `derived_category` from work-description keywords
- `ida.py` — best-effort `district` from the IDA code prefix
- `features.py` — engineered features shared with Phase 3/4
- `prepare_data.py` / `inject_anomalies.py` / `sanity_report.py`

## Data-reality notes (confirmed against the 2026-09-05 exports)

| Field | Reality |
|---|---|
| `Category` | ~97% "Normal/Others" — use `derived_category` instead |
| `district` | not in source; parsed from IDA prefix — **99.1% coverage** |
| start date | absent everywhere — no build-duration features |
| `Average Rating` (completed) | present on 4 of 44,028 rows — unusable |
| `Payment Status` | only "Payment Success" / "Payment In-Progress" |
| Work ID | collides across recommended/completed — not a join key |
| Rajya Sabha | `Constituency` = "Sitting/Nominated Rajya Sabha" — group by State |

## Synthetic anomalies (injected, internal labels only)

| `anomaly_type` | count | how |
|---|---|---|
| `cost_inflation` | 250 | real works cloned, amount ×3–10 above peer-group median |
| `stalled_project` | 150 | recommended works (from MPs with completion rate below median), recommendation 400–1000 days old, no follow-through |
| `contractor_concentration` | ~617 txns / 8 MP-units | one vendor (plausible company name) captures ~65% of an MP's transactions in a constituency |
| `payment_gap` | ~1160 txns / 6 MP-units | burst of large "Payment In-Progress" transactions (~40%+ of the MP's transaction value) |

Synthetic `external_id`s are plain numeric Work IDs drawn from the real ID range
(`[149 .. 311809]`), collision-checked against real IDs, and synthetic vendor
names are ordinary-looking company names — so the rows are indistinguishable
from real ones by any visible field. `is_synthetic_anomaly` /
`anomaly_type` are the **only** internal markers, used only for precision/recall
evaluation and never exposed via API or UI.
