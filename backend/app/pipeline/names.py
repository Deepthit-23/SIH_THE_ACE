"""MP-name normalisation and matching between the works data and the official
allocation PDFs.

The two sources spell the same person differently:

    works data : "Dr. Abhishek Manu Singhvi (2026-32)"      (honorific + term range)
    official   : "ABHISHEK MANU SINGHVI"

Comparing lower-cased alphanumerics (the original approach) matched only 73% of MPs. The
fix is a strict two-pass procedure -- normalise BOTH sides first, fuzzy-match only what is
still unmatched:

  1. exact match on the normalised name (honorifics, parentheticals such as a term range
     "(2026-32)" or an alias "(Rahul Sinha)", punctuation and case removed). Namesakes that
     collide on the normalised name are disambiguated by state.
  2. rapidfuzz token_set_ratio, restricted to the SAME STATE, requiring a unique winner and
     at least 3 tokens on the shorter name (so a 1-2 word name can't "subset-match" anyone).

Everything that is still unmatched is returned as such -- never forced.
"""

from __future__ import annotations

import re

import pandas as pd
from rapidfuzz import fuzz

_PAREN = re.compile(r"\([^)]*\)")
# Leading honorifics only, whole words. "SHRIMANT" (part of a name) must NOT match "SHRI".
_HONORIFIC = re.compile(
    r"^(?:SHRIMATI|SHRI|SRI|SMT|DR|PROF|PROFESSOR|HON'?BLE|KUMARI|KM|ADV|ADVOCATE|"
    r"ER|ENGR|CAPT|COL|MAJ|GEN|REV|MR|MRS|MS)\b\.?\s*",
    re.I,
)
_NON_ALNUM = re.compile(r"[^A-Z0-9]+")

FUZZY_CUTOFF = 90
FUZZY_MIN_TOKENS = 3


def normalize_mp_name(value: object) -> str:
    """Uppercase, parentheticals and leading honorifics stripped, punctuation collapsed."""
    s = _PAREN.sub(" ", str(value or ""))
    s = s.strip()
    prev = None
    while prev != s:                       # "Prof. Dr. X" -> "X"
        prev = s
        s = _HONORIFIC.sub("", s).strip()
    return _NON_ALNUM.sub(" ", s.upper()).strip()


def normalize_state(value: object) -> str:
    s = str(value or "").upper().replace("&", " AND ")
    return _NON_ALNUM.sub(" ", s).strip()


def match_mps(pairs: pd.DataFrame, alloc: pd.DataFrame, cutoff: int = FUZZY_CUTOFF) -> pd.DataFrame:
    """Map each distinct (mp_name, state) in `pairs` to a row of `alloc`.

    `pairs`: columns mp_name, state.  `alloc`: the mp_allocation table (mp_name, state, ...).
    Returns one row per input pair with: alloc_index (index label in `alloc`, NaN if
    unmatched), official_name, method ('normalised' | 'normalised+state' | 'fuzzy' |
    'ambiguous' | 'unmatched') and score (100 for exact, rapidfuzz score for fuzzy).
    """
    a = alloc.copy()
    a["_k"] = a["mp_name"].map(normalize_mp_name)
    a["_s"] = a["state"].map(normalize_state)
    by_key: dict[str, list] = {}
    for idx, k in a["_k"].items():
        by_key.setdefault(k, []).append(idx)

    out = []
    for name, state in pairs[["mp_name", "state"]].drop_duplicates().itertuples(index=False):
        k, s = normalize_mp_name(name), normalize_state(state)
        cands = by_key.get(k, [])
        idx, method, score = None, "unmatched", 0.0

        if len(cands) == 1:
            idx, method, score = cands[0], "normalised", 100.0
        elif len(cands) > 1:                       # namesakes: disambiguate by state
            same = [i for i in cands if a.at[i, "_s"] == s]
            if len(same) == 1:
                idx, method, score = same[0], "normalised+state", 100.0
            else:
                method = "ambiguous"
        else:                                      # pass 2: fuzzy, same state only
            pool = a[a["_s"] == s]
            scored = sorted(
                ((fuzz.token_set_ratio(k, r["_k"]), i, len(k.split()), len(r["_k"].split()))
                 for i, r in pool.iterrows()),
                reverse=True,
            )
            if scored and scored[0][0] >= cutoff and min(scored[0][2], scored[0][3]) >= FUZZY_MIN_TOKENS:
                unique = len(scored) == 1 or scored[1][0] < scored[0][0] - 2
                if unique:
                    idx, method, score = scored[0][1], "fuzzy", float(scored[0][0])
        out.append({
            "mp_name": name, "state": state, "alloc_index": idx if idx is not None else float("nan"),
            "official_name": a.at[idx, "mp_name"] if idx is not None else None,
            "method": method, "score": score,
        })
    return pd.DataFrame(out)
