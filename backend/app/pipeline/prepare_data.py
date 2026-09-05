"""Ingestion: load the four MPLAD source CSVs into PostgreSQL.

Run inside the backend container (recommended):

    docker compose exec backend python -m app.pipeline.prepare_data --reset

or locally from ./backend with a .env pointing at the DB:

    python -m app.pipeline.prepare_data --reset --data-dir ../data

`--reset` drops and recreates every table this project manages -- required the
first time because the Phase 1 schema predates these columns.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import inspect

from app.config import settings
from app.database import Base, engine
from app import models  # noqa: F401  (register tables on Base.metadata)
from app.pipeline.categorize import derive_category
from app.pipeline.ida import parse_district

RAJYA_SABHA = "Rajya Sabha"

FILES = {
    "recommended": "mplads_recommended_works_*.csv",
    "completed": "mplads_completed_works_*.csv",
    "expenditures": "mplads_expenditures_*.csv",
    "mp_summary": "mplads_mp_summary_*.csv",
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _find(data_dir: Path, pattern: str) -> Path:
    matches = sorted(glob.glob(str(data_dir / "raw" / pattern)))
    if not matches:
        raise FileNotFoundError(f"No file matching {pattern!r} in {data_dir / 'raw'}")
    return Path(matches[-1])  # newest by name (dates sort lexically)


def _money(s: pd.Series) -> pd.Series:
    return pd.to_numeric(
        s.astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce"
    )


def _dates(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, errors="coerce", utc=True).dt.date
    return d.where(pd.notna(d), None)


def _bool(s: pd.Series) -> pd.Series:
    m = {"true": True, "false": False, "yes": True, "no": False, "1": True, "0": False}
    return s.astype(str).str.strip().str.lower().map(m)


def _int(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").astype("Int64")


def _write(df: pd.DataFrame, table: str) -> int:
    df = df.astype(object).where(pd.notna(df), None)
    # chunksize kept low: Postgres caps a statement at 65535 bind params and
    # `projects` has ~24 columns (65535 / 24 ≈ 2730).
    df.to_sql(table, engine, if_exists="append", index=False, chunksize=1000, method="multi")
    return len(df)


# --------------------------------------------------------------------------- #
# loaders
# --------------------------------------------------------------------------- #
def load_recommended(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    out = pd.DataFrame()
    out["external_id"] = df["Work ID"].str.strip()
    out["source_file"] = "recommended_works"
    out["work_description"] = df["Work Description"]
    out["category"] = df["Category"]
    out["derived_category"] = df["Work Description"].map(derive_category)
    out["mp_name"] = df["MP Name"].str.strip()
    out["constituency"] = df["Constituency"].str.strip()
    out["state"] = df["State"].str.strip()
    out["house"] = df["House"].str.strip()
    out["is_rajya_sabha"] = out["house"].eq(RAJYA_SABHA)
    out["ida"] = df["IDA"]
    out["district"] = df["IDA"].map(parse_district)
    out["sanctioned_amount"] = _money(df["Recommended Amount (₹)"])
    out["final_amount"] = None
    out["spent_amount"] = None
    out["contractor_name"] = None
    out["start_date"] = None
    out["recommendation_date"] = _dates(df["Recommendation Date"])
    out["completion_date"] = None
    out["status"] = "recommended"
    out["has_images"] = _bool(df["Has Images"])
    out["average_rating"] = None
    out["is_synthetic_anomaly"] = False
    out["anomaly_type"] = None
    return out


def load_completed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    out = pd.DataFrame()
    out["external_id"] = df["Work ID"].str.strip()
    out["source_file"] = "completed_works"
    out["work_description"] = df["Work Description"]
    out["category"] = df["Category"]
    out["derived_category"] = df["Work Description"].map(derive_category)
    out["mp_name"] = df["MP Name"].str.strip()
    out["constituency"] = df["Constituency"].str.strip()
    out["state"] = df["State"].str.strip()
    out["house"] = df["House"].str.strip()
    out["is_rajya_sabha"] = out["house"].eq(RAJYA_SABHA)
    out["ida"] = df["IDA"]
    out["district"] = df["IDA"].map(parse_district)
    out["sanctioned_amount"] = None
    out["final_amount"] = _money(df["Final Amount (₹)"])
    out["spent_amount"] = None
    out["contractor_name"] = None
    out["start_date"] = None
    out["recommendation_date"] = None
    out["completion_date"] = _dates(df["Completed Date"])
    out["status"] = "completed"
    out["has_images"] = _bool(df["Has Images"])
    out["average_rating"] = pd.to_numeric(df["Average Rating"], errors="coerce")
    out["is_synthetic_anomaly"] = False
    out["anomaly_type"] = None
    return out


def load_expenditures(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    out = pd.DataFrame()
    out["mp_name"] = df["MP Name"].str.strip()
    out["constituency"] = df["Constituency"].str.strip()
    out["state"] = df["State"].str.strip()
    out["house"] = df["House"].str.strip()
    out["work_description"] = df["Work Description"]
    out["vendor"] = df["Vendor"].str.strip()
    out["ida"] = df["IDA"]
    out["district"] = df["IDA"].map(parse_district)
    out["amount"] = _money(df["Expenditure Amount (₹)"])
    out["expenditure_date"] = _dates(df["Expenditure Date"])
    out["payment_status"] = df["Payment Status"].str.strip()
    out["is_synthetic_anomaly"] = False
    out["anomaly_type"] = None
    return out


def load_mp_summary(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=True)
    out = pd.DataFrame()
    out["mp_name"] = df["MP Name"].str.strip()
    out["constituency"] = df["Constituency"].str.strip()
    out["state"] = df["State"].str.strip()
    out["house"] = df["House"].str.strip()
    out["allocated_amount"] = _money(df["Allocated Amount (₹)"])
    out["amount_recommended"] = _money(df["Amount Recommended (₹)"])
    out["total_expenditure"] = _money(df["Total Expenditure (₹)"])
    out["utilization_pct"] = pd.to_numeric(df["Utilization %"], errors="coerce")
    out["completed_works"] = _int(df["Completed Works"])
    out["recommended_works"] = _int(df["Recommended Works"])
    out["completion_rate_pct"] = pd.to_numeric(df["Completion Rate %"], errors="coerce")
    out["balance_unpaid"] = _money(df["Balance Not Yet Paid to Vendors (₹)"])
    out["transaction_count"] = _int(df["Transaction Count"])
    out["successful_payments"] = _int(df["Successful Payments"])
    out["pending_payments"] = _int(df["Pending Payments"])
    out["average_rating"] = pd.to_numeric(df["Average Rating"], errors="coerce")
    return out


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reset", action="store_true", help="drop & recreate all tables")
    p.add_argument("--data-dir", default=settings.data_dir, help="path to the data/ dir")
    p.add_argument("--limit", type=int, default=None, help="cap rows per file (debug)")
    args = p.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    print(f"data dir: {data_dir}")
    print(f"database: {engine.url.render_as_string(hide_password=True)}")

    if args.reset:
        print("dropping all tables ...")
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    cols = {c["name"] for c in inspect(engine).get_columns("projects")}
    if "derived_category" not in cols:
        print("ERROR: `projects` is on the old schema. Re-run with --reset.", file=sys.stderr)
        return 1

    plan = [
        ("projects", load_recommended, _find(data_dir, FILES["recommended"])),
        ("projects", load_completed, _find(data_dir, FILES["completed"])),
        ("vendor_transactions", load_expenditures, _find(data_dir, FILES["expenditures"])),
        ("mp_summary", load_mp_summary, _find(data_dir, FILES["mp_summary"])),
    ]

    for table, loader, path in plan:
        print(f"loading {path.name} -> {table} ...")
        df = loader(path)
        if args.limit:
            df = df.head(args.limit)
        n = _write(df, table)
        print(f"  {n:>7,} rows")

    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
