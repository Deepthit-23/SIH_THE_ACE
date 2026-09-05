#!/usr/bin/env python
"""Convenience entrypoint for the ingestion pipeline.

The real implementation lives in `backend/app/pipeline/`. This shim just puts the
backend package on sys.path so you can run it from the repo root:

    python data/prepare_data.py --reset

Inside Docker, prefer:

    docker compose exec backend python -m app.pipeline.prepare_data --reset
"""

import os
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for candidate in (HERE.parent / "backend", Path("/app")):
    if (candidate / "app" / "__init__.py").exists():
        sys.path.insert(0, str(candidate))
        break

os.environ.setdefault("DATA_DIR", str(HERE))

runpy.run_module("app.pipeline.prepare_data", run_name="__main__", alter_sys=True)
