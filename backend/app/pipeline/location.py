"""Where a work is actually located: (work_state, district).

Why this exists. The source data has TWO different geographies per row:
  * `state`    -- the MP's state (for a Rajya Sabha member, the state they were elected from);
  * `district` -- parsed from the implementing-agency (IDA) string, i.e. where the work is carried out,
                  with NO state attached ("HYDERABAD(DISTRICT COLLECTOR HYDERABAD_IDA)").
MPLADS lets members fund works outside their own state (Rajya Sabha nominated members anywhere, elected
members and Lok Sabha members within limits), so `state` != location for ~0.4% of rows, and district
names are not unique across states (Bilaspur HP/CG, Hamirpur HP/UP, Pratapgarh RJ/UP, ...).
Scoping a District Authority on the district NAME alone therefore leaked another state's works (12 Uttar
Pradesh-labelled rows, all physically in Hyderabad, Telangana, belonging to a Rajya Sabha member from UP).

Rule (applied per distinct (mp_state, district) pair):
  1. HOME: the pair is real if
       (a) the Census-2011 reference lists that district under that state (Telangana counts as Andhra
           Pradesh, Ladakh as Jammu & Kashmir, Daman & Diu / Dadra & Nagar Haveli merged -- the 2011 file
           predates those changes), OR
       (b) it dominates that district name among LOK SABHA rows (>= HOME_MIN_ROWS rows and
           >= HOME_MIN_SHARE of them). Lok Sabha members work mostly at home, so this recognises districts
           created or renamed since 2011 (Bengaluru Urban, Kataka, Y.S.R. Kadapa ...).
     work_state = mp_state.
  2. CROSS-STATE: otherwise, if the district name is "home" in exactly ONE state, work_state = that state.
  3. ONLY-STATE: otherwise, if the district name occurs under a single state anywhere in the data, that is
     its state (a small or new district: Namchi, Sepahijala ...). work_state = that state.
  4. UNRESOLVED: anything else (the name exists in several states and none can be shown to be this MP's)
     gets work_state = NULL and location_method = 'unresolved'. It FAILS CLOSED: no State or District scope
     matches a NULL, so only the Ministry (and the MP, by name) can see those works; they still count in
     national totals and are reported as "unlocated". Never guessed.

Rows with no district at all (unparseable IDA) have NO positive location evidence either, so they get the same
treatment: work_state = NULL, location_method = 'no_district' (kept distinct from 'unresolved' for reporting).
They fail closed in exactly the same way and count toward `unlocated_count`.

Deterministic; the reference is DataMeet's Census-2011 district list (CC BY 2.5 India), bundled at
data/reference/districts_2011.csv.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from app.config import settings

HOME_MIN_ROWS = 5
HOME_MIN_SHARE = 0.5

# States that did not exist / were different in the 2011 reference.
_GROUP = {
    "TELANGANA": "ANDHRA PRADESH",
    "LADAKH": "JAMMU AND KASHMIR",
    "DADRA AND NAGAR HAVELI AND DAMAN AND DIU": "DAMAN AND DIU",
    "DADRA AND NAGAR HAVELI": "DAMAN AND DIU",
}


def _n(value: object) -> str:
    return re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper().replace("&", " AND ")).strip()


def _state_key(state: object) -> str:
    s = _n(state)
    s = re.sub(r"^THE ", "", s)
    return _GROUP.get(s, s)


def load_reference(path: Path | None = None) -> set[tuple[str, str]]:
    path = path or Path(settings.data_dir) / "reference" / "districts_2011.csv"
    ref = pd.read_csv(path)
    return {(_state_key(s), _n(d)) for d, s in zip(ref["DISTRICT"], ref["ST_NM"])}


def build_mapping(pairs: pd.DataFrame, reference: set[tuple[str, str]]) -> pd.DataFrame:
    """`pairs`: one row per (state, district, house) with `rows` counts (REAL rows only).
    Returns one row per (state, district): work_state, method ('home' | 'cross_state' | 'unresolved')."""
    ls = pairs[pairs["house"] == "Lok Sabha"]
    ls_by = ls.groupby(["district", "state"])["rows"].sum().reset_index()
    ls_by["share"] = ls_by["rows"] / ls_by.groupby("district")["rows"].transform("sum")
    dominant = {
        (r.state, r.district)
        for r in ls_by.itertuples() if r.rows >= HOME_MIN_ROWS and r.share >= HOME_MIN_SHARE
    }

    def is_home(state: str, district: str) -> bool:
        return (_state_key(state), _n(district)) in reference or (state, district) in dominant

    all_pairs = pairs[["state", "district"]].drop_duplicates()
    states_per_name = all_pairs.groupby("district")["state"].nunique().to_dict()
    home_states: dict[str, set[str]] = {}
    for st, d in all_pairs.itertuples(index=False):
        if is_home(st, d):
            home_states.setdefault(d, set()).add(st)

    out = []
    for st, d in all_pairs.itertuples(index=False):
        if is_home(st, d):
            out.append((st, d, st, "home"))
        elif len(home_states.get(d, ())) == 1:
            out.append((st, d, next(iter(home_states[d])), "cross_state"))
        elif states_per_name.get(d, 0) == 1:
            out.append((st, d, st, "only_state"))
        else:
            out.append((st, d, None, "unresolved"))
    return pd.DataFrame(out, columns=["state", "district", "work_state", "method"])


# --------------------------------------------------------------------------- #
# database side
# --------------------------------------------------------------------------- #
def ensure_columns(engine) -> None:
    """Additive, idempotent: give databases created before this fix the location columns."""
    from sqlalchemy import text

    # Check the catalog first: `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` takes an ACCESS EXCLUSIVE lock even
    # when the column exists, so running it on every startup can queue behind (and block) any open reader.
    wanted = {"work_state": "varchar(128)", "location_method": "varchar(16)"}
    with engine.connect() as c:
        have = {(r[0], r[1]) for r in c.execute(text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_name IN ('projects', 'vendor_transactions') AND column_name IN ('work_state', 'location_method')"))}
    todo = [(t, col, typ) for t in ("projects", "vendor_transactions") for col, typ in wanted.items()
            if (t, col) not in have]
    if not todo:
        return
    with engine.begin() as c:
        for t, col, typ in todo:
            c.execute(text(f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {col} {typ}"))
        for t in ("projects", "vendor_transactions"):
            c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{t}_work_state ON {t} (work_state)"))


def ensure_derived(engine) -> bool:
    """Startup safety net: a database that was never derived (fresh restore of an old dump, new rows) would
    fail every State/District scope closed, so derive it now. Returns True if it had to run."""
    from sqlalchemy import text

    ensure_columns(engine)
    with engine.connect() as c:
        pending = c.execute(text(
            "SELECT EXISTS (SELECT 1 FROM projects WHERE location_method IS NULL) "
            "OR EXISTS (SELECT 1 FROM vendor_transactions WHERE location_method IS NULL)"
        )).scalar()
    if pending:
        apply_to_db(engine)
    return bool(pending)


def apply_to_db(engine, reference: set[tuple[str, str]] | None = None) -> dict:
    """Derive and store work_state + location_method for every projects / vendor_transactions row.

    Idempotent. The mapping is learned from REAL rows only (synthetic fixtures clone real rows'
    state/district, so they resolve through the same pairs).
    """
    from sqlalchemy import text

    ensure_columns(engine)
    reference = reference if reference is not None else load_reference()
    pairs = pd.read_sql(
        """
        SELECT state, district, house, count(*) AS rows FROM (
            SELECT state, district, house FROM projects WHERE NOT is_synthetic_anomaly
            UNION ALL
            SELECT state, district, house FROM vendor_transactions WHERE NOT is_synthetic_anomaly
        ) u WHERE state IS NOT NULL AND district IS NOT NULL
        GROUP BY state, district, house
        """,
        engine,
    )
    mapping = build_mapping(pairs, reference)

    with engine.begin() as c:
        c.execute(text("CREATE TEMP TABLE _loc_map (state text, district text, work_state text, method text) ON COMMIT DROP"))
        c.execute(
            text("INSERT INTO _loc_map (state, district, work_state, method) VALUES (:s, :d, :w, :m)"),
            [{"s": r.state, "d": r.district, "w": r.work_state, "m": r.method} for r in mapping.itertuples()],
        )
        for table in ("projects", "vendor_transactions"):
            c.execute(text(f"UPDATE {table} SET work_state = NULL, location_method = NULL"))
            c.execute(text(f"UPDATE {table} SET work_state = NULL, location_method = 'no_district' "
                           f"WHERE district IS NULL AND state IS NOT NULL"))
            c.execute(text(
                f"UPDATE {table} t SET work_state = m.work_state, location_method = m.method FROM _loc_map m "
                f"WHERE t.state = m.state AND t.district = m.district"))
            # anything still unlabelled (e.g. no state at all) fails closed
            c.execute(text(f"UPDATE {table} SET location_method = 'unlocated' WHERE location_method IS NULL"))
    joined = pairs.merge(mapping, on=["state", "district"])
    by_method = {k: int(v) for k, v in joined.groupby("method")["rows"].sum().items()}
    moved = joined[(joined["work_state"].notna()) & (joined["work_state"] != joined["state"])]
    return {
        "rows_considered": int(joined["rows"].sum()), "by_method": by_method,
        "relocated_rows": int(moved["rows"].sum()),
        "relocated_pairs": int(((mapping["work_state"].notna()) & (mapping["work_state"] != mapping["state"])).sum()),
        "unresolved_pairs": int((mapping["method"] == "unresolved").sum()),
        "mapping": mapping, "detail": joined,
    }


def write_report(stats: dict, path: Path | None = None) -> Path:
    path = path or Path(settings.data_dir) / "processed" / "location_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    d = stats["detail"]
    moved = d[d["work_state"].notna() & (d["work_state"] != d["state"])].groupby(["state", "district", "work_state"])["rows"].sum().sort_values(ascending=False)
    un = d[d["method"] == "unresolved"].groupby(["state", "district"])["rows"].sum().sort_values(ascending=False)
    lines = [
        "# Work location (work_state) derivation",
        "",
        f"Rows considered (real, with a district): {stats['rows_considered']:,}",
        "By method: " + ", ".join(f"{k} {v:,}" for k, v in stats["by_method"].items()),
        f"Relocated (work_state != MP state): {stats['relocated_rows']:,} rows across {stats['relocated_pairs']} (state, district) pairs",
        "",
        "## Relocated pairs (top 25)", "", "| MP state | district | work state | rows |", "|---|---|---|--:|",
        *[f"| {s} | {di} | {w} | {n:,} |" for (s, di, w), n in moved.head(25).items()],
        "", f"## Unresolved: {int(un.sum()):,} rows, {len(un)} pairs -> work_state NULL, FAIL CLOSED "
        "(invisible to every State/District scope; Ministry and the MP by name only)", "",
        "| MP state | district | rows |", "|---|---|--:|",
        *[f"| {s} | {di} | {n:,} |" for (s, di), n in un.head(25).items()],
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    from app.database import engine

    stats = apply_to_db(engine)
    out = write_report(stats)
    print(f"work_state set. {stats['by_method']}; relocated {stats['relocated_rows']:,} rows "
          f"in {stats['relocated_pairs']} pairs. report -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
