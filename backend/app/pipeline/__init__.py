"""Shared data-pipeline logic: categorization, IDA parsing, feature engineering.

Imported by both the ingestion scripts and the backend API / ML modules so the
same transformations are applied everywhere.
"""

from datetime import date

# Snapshot date of the source exports (from the filenames, mplads_*_2026-09-05).
# Used as "today" for age / staleness calculations so results are reproducible.
SNAPSHOT_DATE = date(2026, 9, 5)
