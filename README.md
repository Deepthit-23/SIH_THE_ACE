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
docker compose exec backend python -m app.pipeline.prepare_data --reset      # load CSVs + official allocation PDFs + demo users
docker compose exec backend python -m app.pipeline.inject_anomalies --clear  # synthetic anomalies (all 6 types)
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
docker compose exec backend python -m pytest                       # 159 tests incl. RBAC, state/district location scoping, user management, map/graph feeds
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
    routers/            health, meta, projects, risk, patterns, audit, cases
    audit.py            SHA-256 hash-chain (build / verify / cache)
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
| `GET /risk-scores` | ranked list — sortable, filterable (min_score, category, state, district, status, **case_status**), **`q` free-text search** (MP / work / Work ID) |
| `GET /risk-scores/export.csv` | flagged list as CSV (same filters), for offline audit work |
| `GET /projects/{id}` | full project + ordered explanation + score breakdown + case status |
| `PUT /projects/{id}/case` | set review status (`pending`/`under_review`/`confirmed`/`dismissed`); a note is required to dismiss |
| `GET /projects/{id}/case`, `GET /projects/{id}/case/history` | current review state / full history (also in the audit chain) |
| `GET /cases` | case log — every project an auditor has acted on |
| `GET /patterns/districts`, `GET /patterns/contractors` | cross-entity rankings for the pattern charts |
| `GET /districts/{d}/pattern`, `GET /contractors/{v}/pattern` | single-entity drill-in |
| `GET /meta/summary` | national headline figures (allocated / spent / completion / flag counts) |
| `GET /meta/filters` | filter option lists + score-band counts |
| `GET /admin/users`, `POST /admin/users`, `PATCH /admin/users/{id}`, `GET /admin/scope-options` | **Ministry only** (403 for every other role): list / create / deactivate-reactivate-reset-password users; scope choices from the data |
| `POST /auth/change-password` | self-service; the only way out of `must_change_password` |
| `GET /audit/recent` | newest audit entries (id, type, hash, previous hash, timestamp; never payloads) for the chain widget |
| `GET /patterns/states` | per-state flagged share / average score / counts (scoped) for the map |
| `GET /patterns/network` | strongest flagged MP-vendor concentration relationships (scoped) for the network graph |
| `GET /audit/verify` | walk the hash-chain → `{valid, entries_checked, broken_at, cached}` (cached on a table fingerprint) |

## How scoring works

1. **Rule engine** (`rules.py`) — six independent rules, each a boolean + a
   plain-language reason:
   cost anomaly (z-score vs `derived_category`+district peers), contractor
   concentration (one vendor's share of an MP's transactions), stalled/ghost project
   (old recommendation, no completion/payment activity; suppressed for MPs in office
   < 18 months), payment gap (in-progress payment share vs utilisation),
   **allocation ceiling breach** (MP's committed total vs the *official* ceiling from the
   supplied PDFs; projects are taken in date order with a running total, and only those that push it past the ceiling (2% tolerance) are flagged; MPs with no official ceiling are
   not-applicable rather than zero) and **duplicate work** (same MP + constituency,
   near-identical *rare-token* description, amounts within 15% **and** dates >= 30 days
   apart; generic phrases and corpus-common words are stripped so boilerplate cannot
   drive a match; series such as "Sl. No. 1-150" vs "151-300" and same-Work-ID pairs are
   not duplicates).
2. **Isolation Forest** (`ml_model.py`) — unsupervised, 30 engineered features
   (including ceiling utilisation and duplicate max-similarity: the rules' *raw* signals, never
   their flags). The synthetic-anomaly labels are **never** a model input. Explanation =
   ranked feature deviations in plain language; fragments a fired rule already states are dropped.
3. **Combiner** (`risk_scorer.py`) — rule points, **measured rather than guessed**: points fall
   log-linearly with the flag rate on real rows, anchored on cost 2.2% -> 40 and stalled 8.5% -> 15,
   capped at 45. Result: ceiling 45, cost 40, contractor 30, payment 25, stalled 15, and duplicate 35.
   **Duplicate's 35 is a deliberate manual override, not the formula's output** (which was ~49-50,
   i.e. 45 after the cap). Flag rate is only a proxy for false-positive rate, and review of the
   flagged samples found many plausible legitimate repeat purchases even after the text,
   amount, boilerplate and date-gap filters. 35 keeps duplicate below cost anomaly (40, the
   longer-scrutinised rule) while still above payment gap (25) and stalled (15).
   Plus a smooth-knee ML contribution (only where it can show a reason) and a cost-z tie-breaker
   -> one `combined_risk_score` (0-100) and one ordered explanation list.
   Bands: **>= 70 high · 50-69 medium · < 50 low**.
4. **Auditor workflow** (`cases.py`) — each project has a review status
   (`pending → under_review → confirmed → dismissed`), settable from the detail
   view; dismissing requires a reason. Every change is also appended to the audit
   hash-chain, so review decisions are as tamper-evident as scores. Dismissal
   reasons are the feedback loop a production system would use to tune thresholds
   or retrain (that part is not built — just the logging).
5. **Audit chain** (`audit.py`) — every `score_projects` run appends one
   SHA-256-chained `audit_log` entry per project:
   `this_hash = sha256(canonical_payload + previous_hash)` (genesis = 64 zeros).
   Altering any past entry breaks every hash after it; `GET /audit/verify`
   detects it and reports `broken_at`. Results are cached on a cheap in-DB table
   fingerprint (no re-hashing 131k rows per page load; invalidates the instant
   any row changes). The dashboard header shows a live
   "Audit trail verified ✓" chip.

## Validation (synthetic anomalies)

Real MPLAD fraud isn't labelled, so `inject_anomalies` appends synthetic rows for **all six**
rule types, tagged `is_synthetic_anomaly` / `anomaly_type` **internally only** — never in any
API payload (asserted by test). Scoring is deterministic (fixed seed, `ORDER BY id`; verified by
scoring twice and diffing). Latest run (`data/processed/rule_eval.md` / `ml_eval.md`); FP = flagged
share of *real* rows, excluding units that host injected cases:

| anomaly type | injected | rule recall | + ML (combined) | FP on real data |
|---|--:|--:|--:|--:|
| cost_inflation | 250 | 81.6% | 90.0% | 2.2% of projects |
| stalled_project | 150 | 68.0% | 70.0% | 8.5% of recommended |
| allocation_ceiling_breach | 96 projects / 12 MPs | 100% of MPs (12/12); crossing rows may be real later-dated projects | 100% of MPs | 1 real project outside host MPs (1 of 720 MPs) |
| duplicate_work | 120 | 82.5% | 82.5% | 1.3% of projects |
| contractor_concentration | 8 MP units | 100% | 100% | 0.6% of groups |
| payment_gap | 6 MP units | 100% | 100% | 2.9% of groups |

Notes on the two newer rules:

- **Duplicate work** was tuned against real data: text-only matching flagged **41.1%** of real
  projects; adding the amount gate + rare-token filter -> 6.6%; adding the 30-day date gap -> **1.3%**.
  Much of what remains is still plausibly legitimate repeat purchasing, so treat it as a review
  prompt. Recall misses (21/120) are short descriptions with < 2 distinctive tokens — by design.
- **Ceiling breach** flags only the projects that push an MP's date-ordered running total past
  the official ceiling (the crossing project and any later ones adding to the excess); the
  portfolio committed before the crossing is not flagged. This cut ceiling flags from 3,675 to 383
  rows and the combined `>= 70` count from 5,426 to 4,078. Injected fixtures other than the
  breach cases are excluded from the running total.
- **Official-ceiling matching**: works-data MPs are matched to the PDFs by normalising both sides
  (honorifics, "(2026-32)" suffixes, case, punctuation), then same-state fuzzy for the remainder:
  732 of 733 MPs (99.93% of projects). The one unmatched MP (Dr. Dinesh Sharma, UP Rajya Sabha,
  term 2023-26) is not in the official list. One official row (Chavan Vasantrao Balwantrao) has no
  published ceiling. See `data/processed/allocation_reconciliation.md` and `allocation_discrepancies.csv`.

- **Open question — Delkar's ceiling.** Both Lok Sabha seats of Dadra & Nagar Haveli and Daman &
  Diu are present in the works data, `mp_summary` and the official PDF (Kalaben Mohanbhai Delkar,
  Dadra & Nagar Haveli, 2 works; Patel Umeshbhai Babubhai, Daman & Diu, 61 works), so neither is
  missing or unmatched. Delkar's official ceiling is Rs 26.95 Cr (1.83x the standard Rs 14.70 Cr)
  while `mp_summary` holds Rs 14.70 Cr for her; **this difference is unexplained from the
  available sources.** The ceiling rule uses the official figure as published. All eleven MPs whose
  `mp_summary` allocation differs from the official one have the official figure higher
  (`data/processed/allocation_discrepancies.csv`); the cause is likewise not established.

Combined `score >= 70` flags **2.9%** of real projects (3,864 of 131,300).

## Demo anchor projects

Navigate straight to `/projects/<id>`. Regenerate with
`docker compose exec backend python -m app.pipeline.demo_anchors`
(→ `data/processed/demo_anchors.md`) after any pipeline re-run.

| anchor | id | what it shows | score |
|---|---|---|--:|
| cost anomaly | **131836** | cost 8.8x the road-paving average; cost rule is the driving signal | 95 |
| contractor concentration | **60625** | one vendor holds 64% of an MP's transactions, alongside a 30x cost overrun | 96 |
| stalled / ghost | **131953** | the deliberately weak signal (15 points): old recommendation, no activity | 15 |
| payment gap | **131799** | 89% of the MP's payment value still in-progress | 96 |
| ceiling breach | **132186** | the project that pushed the MP's running total past the official ceiling (ceiling rule alone) | 72 |
| duplicate work | **132303** | near-identical re-claim of an earlier work (counterpart **39444**); weight 35 | 76 |
| ML-only (new features) | **9356** | no rule fired; the model cites duplicate similarity | 78 |

Role walkthrough (each opens with the demo account for that role; scope walls verified against the
live API): **Ministry** 124738 (outside every other demo scope, three rules incl. duplicate),
**State** 83123 (Telangana), **District** 10360 (Hyderabad), **MP** 176 (Singhvi's portfolio).
Full detail, the access matrix and the case-review script: `data/processed/demo_anchors.md`.

_(synthetic project ids shift if `inject_anomalies` re-runs; regenerate `demo_anchors` afterwards.
Real projects such as 60625, 10360, 83123, 176 and 124738 keep their ids.)_

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
- **No production security hardening.** Auth is real (bcrypt + JWT, server-side role/scope
  enforcement) but uses seeded demo accounts and a demo JWT secret; no OAuth/SSO, rate limiting
  or secret management. Not production-ready.
- **No live scraping.** Data is loaded from static CSV exports.
- **No MLOps / model retraining pipeline.** The model is retrained in-process on
  each `score_projects` run with a fixed seed. Auditor dismissal reasons are
  *logged* (see the case log) as the feedback such a pipeline would consume — the
  consumption itself isn't built.
- **No deep mobile responsiveness.** Designed for a desktop auditor workflow.
- **No DB migrations (Alembic).** `score_projects` runs additive `ALTER`s /
  `create_all`; acknowledged tech debt, low prototype value.

### Candidate next steps (not built)

- **Perceptual-hash duplicate-photo detection** across the eSAKSHI work images —
  novel, but needs the image URLs to be reachable; worth a time-boxed feasibility
  spike first.
- **Trend view** — a project's risk score over two data snapshots, turning this
  from a static report into a monitoring system. Needs a second time-separated
  export.

Flags are decision-support for auditors, **not** findings of wrongdoing.
# MPLAD anomaly & fraud detection prototype

## Data provenance

`mp_summary` is derived from public MPLADS exports obtained via empoweredindian.in. It is not the official SIH allocation source. `mp_allocation` is populated only from the supplied official SIH PDFs (`Allocated_Limit_for_Honble_MPs__1_.pdf` and `...__2_.pdf`); the ingestion command writes a match-rate and reconciliation report instead of silently merging discrepancies.

## Demo access (prototype only)

| Role | Username | Password | Scope |
|---|---|---|---|
| Ministry | `ministry_demo` | `DemoMinistry!2026` | National |
| State nodal | `state_demo` | `DemoState!2026` | Telangana |
| District authority | `district_demo` | `DemoDistrict!2026` | HYDERABAD |
| MP self | `mp_demo` | `DemoMP!2026` | Abhishek Manu Singhvi |

Passwords are bcrypt-hashed and JWTs are verified server-side. Replace the demo JWT secret and all accounts before any non-demo use. State and district users may confirm/dismiss cases within their scope; the ministry can override any decision (a ministry decision is locked against non-ministry users); MP accounts are read-only. Scope is enforced server-side on every endpoint (exact, case-insensitive match on state / district / MP name).

## User management (Ministry only)

The Ministry role can provision accounts from the **User Management** page (nav item shown to the
Ministry only) or the `/admin/*` API:

- **Create** (username, role, scope, temporary password). The scope is validated against the real
  data (a state / district / MP that does not exist is rejected, and it is stored in the data's own
  casing), the password is bcrypt-hashed, and the account is flagged `must_change_password`.
- **Deactivate / reactivate**: takes effect on the very next request, including for tokens already
  issued (every request re-reads the account). You cannot deactivate yourself or the last active
  Ministry account.
- **Reset password**: sets a new temporary password and forces a change at next sign-in.
- **First login**: until the temporary password is replaced, the server answers `403
  password_change_required` on every endpoint except `/auth/me` and `/auth/change-password`, so this
  is enforced server-side, not just by the UI. There is no password-policy engine: minimum 8
  characters and it must differ from the temporary one.
- **Audit**: every create / deactivate / reactivate / reset appends an `admin_action` entry to the
  same SHA-256 hash-chain as scores and case reviews, in the same transaction as the change (actor,
  target, role, scope; never a password or hash). A user's own password change is not an admin
  action and is not chained.
- The four demo accounts stay seeded. Startup adds any missing ones but does not touch an existing
  account's password or active flag, so a Ministry decision is not undone by a restart.
- Existing databases are upgraded in place (`ALTER TABLE users ADD COLUMN IF NOT EXISTS ...`, run at
  startup); a dump taken before this feature restores fine and upgrades when the backend next starts.
- The temporary password is shown to the admin once, in the browser, so it can be handed over out of
  band; there is no email/SMS delivery.

## Analytical views

- **Project timeline** (project detail): recommended -> completed -> first flagged -> case reviewed, with the
  elapsed time on each step. "First flagged" is the earliest scoring run on record (from the audit chain);
  `risk_flags.flagged_at` is rewritten on every re-score, so it is shown only as "re-scored on ...". The
  detail endpoint gained `flagged_at` / `first_flagged_at` for this (data was already stored).
- **Duplicate side-by-side** (project detail, when `duplicate_work` fired): this project vs its matched
  counterpart, word-level diff, text similarity, amount gap and date gap. The rule now records
  `counterpart_id` and `similarity` on its explanation item. The counterpart is fetched through the normal
  scoped project endpoint, so if it sits outside the viewer's scope (67 pairs cross a district boundary)
  the panel says so and shows the stored similarity only.
- **Audit chain widget** (sidebar): the newest 6 audit entries as linked blocks (truncated hash,
  timestamp, event type), refreshed every 20 s. It shows the chain's structure; the pass/fail verdict over
  the whole chain remains the header badge.
- **State choropleth** (Patterns page): colour by flagged share (score >= 50) or average score; ranked list
  alongside; click a state to open its projects. Scoped server-side: a State user gets only their state,
  a District/MP user gets only the projects in their own scope.
- **Contractor-MP network** (Patterns page): only the relationships the concentration rule flags (a vendor
  holding >= 40% of an MP unit's transactions), top N (20-150) by share; line width = transaction value;
  hover isolates a node, click pins its details. Note the data's shape: flagged relationships are almost
  all one-to-one (top 40 = 40 MP units, 39 contractors), so the graph is mostly isolated pairs, not a web.
  `/patterns/contractors` was not enough (vendor totals only, no MP links), hence `/patterns/network`.

### State map data

Boundaries: DataMeet India community, `datameet/maps` (`States/Admin2.shp`), **CC BY 4.0** (per the
repository README; attribution is shown under the map and in `frontend/src/assets/india-states.LICENSE.txt`).
The file is current (36 states/UTs including Telangana, Ladakh and the merged Dadra & Nagar Haveli and Daman
& Diu). Geometry was simplified (1.5%, ~277 KB) and re-wound for d3-geo; no boundary was edited.

Name matching (our `projects.state` vs the GeoJSON `ST_NM`), run before any rendering: **36 of 36 matched,
100% of the 131,916 projects covered, one-to-one in both directions.** 33 matched exactly; 3 needed only
`&`/`and`, "The" and "Islands" normalisation (Andaman & Nicobar, Jammu & Kashmir, Dadra & Nagar Haveli and Daman
& Diu). The canonical name is baked into each feature, so the runtime join is plain equality.

Caveats: the map is illustrative. Depiction of India's external boundary (notably Jammu & Kashmir and
Ladakh) should be checked against Survey of India requirements before any public release. Rates for very
small states/UTs rest on few projects (e.g. Dadra & Nagar Haveli and Daman & Diu: 63). The map, the state
filter and the district chart use where the work is LOCATED (see "Work location and scoping").

## Work location and scoping

**The data has two geographies per row.** `state` is the MP's state (for a Rajya Sabha member, the state they
were elected from); `district` is parsed from the implementing-agency (IDA) string, i.e. where the work is
done, and carries **no state**. MPLADS lets members fund works outside their state, so the two can differ, and
district names repeat across states (Bilaspur HP/CG, Hamirpur HP/UP, Pratapgarh RJ/UP, ...).

**The bug this caused.** A District Authority was scoped on the district name alone, so "HYDERABAD" also saw
12 projects labelled Uttar Pradesh. Root cause, checked against the raw CSV: not an IDA-parsing collision
(the string is literally `HYDERABAD(DISTRICT COLLECTOR HYDERABAD_IDA)`) but a genuine cross-state work: all 12
belong to one Rajya Sabha member elected from Uttar Pradesh whose works are in Hyderabad, Telangana.

**The scoping hierarchy now nests**

| Role | Scope | Column |
|---|---|---|
| Ministry | national | none |
| State | the state the work is located in | `work_state` |
| District | the (state, district) pair | `work_state` + `district` |
| MP | their own portfolio, wherever it is located | `mp_name` |

Every District scope is inside its State scope by construction (same column), which is asserted against the data.
State officers therefore see works *implemented in their state*, including other states' MPs' works there, and do
not see their own MPs' works implemented elsewhere. MP-level allocation figures (header tiles) stay keyed on the
MP's own state, since allocations are per MP.

**How `work_state` is derived** (`backend/app/pipeline/location.py`; runs in `prepare_data` and
`inject_anomalies`, and automatically at startup if a database has never been derived; or
`python -m app.pipeline.location`, which also writes `data/processed/location_report.md`). Per (MP state,
district) pair:
1. **home**: the Census-2011 district list (`data/reference/`, DataMeet, CC BY 2.5 India) confirms it, or it
   dominates that district name among Lok Sabha rows (>= 5 rows and >= 50%; recognises districts created since 2011);
2. **cross_state**: otherwise, if the name is "home" in exactly one state, the work is relocated there;
3. **only_state**: otherwise, if the name occurs under a single state anywhere in the data, that state (small or
   new districts such as Namchi, Sepahijala);
4. **unresolved**: anything else (a multi-state name none of whose homes is provably this MP's) gets
   `work_state = NULL`, `location_method = 'unresolved'`.

Rows with **no district recorded at all** (unparseable IDA) have no positive location evidence either, so they
get the same treatment: `work_state = NULL`, `location_method = 'no_district'` (kept distinct for reporting).

Current data (projects / vendor transactions): home 129,907 / 107,302; cross_state 711 / 526; only_state 50 / 37;
**no_district 1,238 / 2,602; unresolved 10 / 3**. The unresolved works are three Rajya Sabha members' works in a
"Bilaspur", "Pratapgarh" or "Hamirpur" that exists in several states. (1,775 of the no-district vendor
transactions are injected test fixtures, which were created without a district.)

**Works with no positive location fail closed** (both sets above, identically). A NULL location matches no
State or District scope, so those works are visible only to the Ministry and to the MP who owns them (by name).
They still count in national totals, and the state aggregates report them as `unlocated_count` (1,248 projects;
national totals reconcile: states + unlocated = all projects). The risk list shows "location unresolved" (has a
district) or "no location recorded" (has none); the map footnote says how many are not placed. The cost: about 1%
of each state's portfolio (works whose IDA could not be parsed) is not in that state's officer's view; they are
in the Ministry's.
`work_state` is never used with a fallback to `state`, so a database that has not been derived also fails closed
(startup derives it).

**Where the location is used.** District and State scoping (every path: list, detail, cases, search, CSV
export, aggregates, map, contractor network), the risk-list state filter and its options, the state map, the
district chart/drill-down (grouped by state + district), and the admin panel (a district account is created from
a (state, district) pair; one dropdown entry per pair). The project page shows "Work location" when it differs
from the MP's state. The state map is drawn for the Ministry and State roles only; District and MP users get a
summary card headed by their full scope (e.g. "HYDERABAD, Telangana"), because colouring a whole state from a
narrower scope's numbers would misstate it.

## Pipeline

Run in this order: `docker compose exec backend python -m app.pipeline.prepare_data --reset` (loads CSVs, ingests the official allocation PDFs, seeds demo users); `docker compose exec backend python -m app.pipeline.inject_anomalies --clear`; `docker compose exec backend python -m app.pipeline.score_projects`; `docker compose exec backend python -m app.pipeline.evaluate_rules`.

## Out of scope

Real-time source integration, production OAuth/secret management, perceptual image hashing, and a genuine historical trend series are deliberately not implemented. Risk flags remain append-oriented; the interface must say when only one snapshot is available.
