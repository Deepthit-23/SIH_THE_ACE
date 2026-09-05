"""Parse a best-effort district name from the MPLAD `IDA` code string.

Examples seen in the data:
    "UDALGURI(DEPUTY COMMISSIONER Udalguri_IDA)"  -> UDALGURI
    "CHITTOOR(DISTRICT COLLECTOR CHITTOOR_IDA)"   -> CHITTOOR
    "TAMULPUR(IDA Tamulpur)"                      -> TAMULPUR

The token before the first "(" is the district-level implementing agency code.
Source casing is inconsistent ("AGRA" vs "Ahmedabad") so we uppercase.
Rows that don't fit the pattern return None.
"""

import re

_prefix_re = re.compile(r"^\s*([A-Za-z][A-Za-z .&'-]+?)\s*\(")


def parse_district(ida: str | None) -> str | None:
    if not ida or not str(ida).strip():
        return None
    m = _prefix_re.match(str(ida))
    if not m:
        # No parenthesis -- take the whole string if it looks like a place name.
        raw = str(ida).strip()
        return raw.upper() if raw and len(raw) <= 60 else None
    district = m.group(1).strip().upper()
    # Guard against garbage.
    if len(district) < 2 or len(district) > 60:
        return None
    return district
