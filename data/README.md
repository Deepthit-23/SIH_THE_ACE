# Data

- `raw/` — original MPLAD project exports (from mplads.gov.in or a representative
  sample). Git-ignored; not committed. **Provided by the team, not fabricated.**
- `processed/` — normalized CSVs written by the prep script. Git-ignored.
- Scripts (`prepare_data.py`, synthetic anomaly injector, feature engineering)
  land here in Phase 2.

## Expected raw format

_TBD — the team will supply the source file. The prep script will map its columns
onto the `projects` schema:_ `mp_name, constituency, state, district, category,
sanctioned_amount, spent_amount, contractor_name, start_date, completion_date,
status`.
