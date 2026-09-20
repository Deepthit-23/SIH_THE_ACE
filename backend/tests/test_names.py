"""MP-name normalisation and matching against the official allocation rows."""

import pandas as pd

from app.pipeline.names import match_mps, normalize_mp_name


def test_normalise_strips_honorifics_and_term_suffix():
    assert normalize_mp_name("Dr. Abhishek Manu Singhvi (2026-32)") == "ABHISHEK MANU SINGHVI"
    assert normalize_mp_name("Prof. Dr. K. Rao") == "K RAO"
    assert normalize_mp_name("Smt. Maya Naroliya (2020-26)") == "MAYA NAROLIYA"


def test_normalise_does_not_eat_name_starting_like_an_honorific():
    assert normalize_mp_name("SHRIMANT PATIL") == "SHRIMANT PATIL"
    assert normalize_mp_name("DRAVID KUMAR") == "DRAVID KUMAR"


def _alloc(*rows):
    return pd.DataFrame([{"mp_name": n, "state": s} for n, s in rows])


def test_exact_after_normalisation():
    m = match_mps(pd.DataFrame([{"mp_name": "Shri Ravi Kumar (2026-32)", "state": "Telangana"}]),
                  _alloc(("RAVI KUMAR", "Telangana")))
    assert m.loc[0, "method"] == "normalised" and m.loc[0, "alloc_index"] == 0


def test_namesakes_disambiguated_by_state():
    a = _alloc(("RAVI KUMAR", "Bihar"), ("RAVI KUMAR", "Telangana"))
    m = match_mps(pd.DataFrame([{"mp_name": "Ravi Kumar", "state": "Telangana"}]), a)
    assert m.loc[0, "method"] == "normalised+state" and m.loc[0, "alloc_index"] == 1


def test_fuzzy_only_within_same_state_and_never_across_states():
    a = _alloc(("VENKATA RAMANA REDDY", "Telangana"), ("VENKATA RAMANA REDDY", "Bihar"))
    ok = match_mps(pd.DataFrame([{"mp_name": "Venkata Ramana Reddi", "state": "Telangana"}]), a)
    assert ok.loc[0, "method"] == "fuzzy" and ok.loc[0, "alloc_index"] == 0
    none = match_mps(pd.DataFrame([{"mp_name": "Venkata Ramana Reddi", "state": "Kerala"}]), a)
    assert none.loc[0, "method"] == "unmatched"


def test_short_names_never_fuzzy_match():
    a = _alloc(("RAVI KUMAR SINGH", "Telangana"))
    m = match_mps(pd.DataFrame([{"mp_name": "Ravi", "state": "Telangana"}]), a)
    assert m.loc[0, "method"] == "unmatched"
