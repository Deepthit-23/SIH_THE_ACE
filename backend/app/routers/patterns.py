"""District- and contractor-level aggregation for the pattern view.

All queries select explicit columns -- `is_synthetic_anomaly` / `anomaly_type`
are never referenced here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import current_user, scope_label, scope_sql
from app.database import get_db
from app.models import User
from app.pipeline.rules import (
    CONTRACTOR_MIN_UNIT_TXNS,
    CONTRACTOR_MIN_VENDOR_TXNS,
    CONTRACTOR_SHARE_THRESHOLD,
)
from app.schemas import (
    ContractorPattern,
    ContractorUnitShare,
    DistrictCategoryStat,
    DistrictPattern,
    PatternRankList,
    PatternRankRow,
)

router = APIRouter(tags=["patterns"])


def _unit_scope(user: User) -> tuple[str, dict]:
    """Restrict vendor_transactions rows to the (MP, constituency) units that touch
    the caller's scope. Whole units are kept so concentration shares stay correct
    (a district user still sees an MP's true share, not a district-truncated one)."""
    cond, params = scope_sql(user, "s")
    if not cond:
        return "", {}
    return (
        " AND EXISTS (SELECT 1 FROM vendor_transactions s WHERE s.mp_name = vt.mp_name "
        "AND s.constituency IS NOT DISTINCT FROM vt.constituency" + cond + ")",
        params,
    )



# --------------------------------------------------------------------------- #
# Cross-entity rankings (for the pattern-view charts)
# --------------------------------------------------------------------------- #
@router.get("/patterns/districts", response_model=PatternRankList)
def rank_districts(
    db: Session = Depends(get_db), user: User = Depends(current_user),
    limit: int = Query(20, ge=1, le=100),
    threshold: float = Query(70, ge=0, le=100),
) -> PatternRankList:
    scope, sparams = scope_sql(user, "p")
    rows = db.execute(
        text(
            f"""
            SELECT COALESCE(NULLIF(p.district, ''), '(unknown)') AS key,
                   p.work_state AS st,
                   count(*) AS project_count,
                   avg(rf.combined_risk_score) AS avg_risk,
                   count(*) FILTER (WHERE rf.combined_risk_score >= :thr) AS high_risk
            FROM projects p
            JOIN risk_flags rf ON rf.project_id = p.id
            WHERE p.work_state IS NOT NULL{scope}
            GROUP BY 1, 2
            ORDER BY high_risk DESC, avg_risk DESC
            LIMIT :lim
            """
        ),
        {"thr": threshold, "lim": limit, **sparams},
    ).all()
    return PatternRankList(
        dimension="district",
        items=[
            PatternRankRow(
                key=r.key,
                state=r.st,
                project_count=r.project_count,
                avg_risk_score=round(float(r.avg_risk or 0), 1),
                high_risk_count=r.high_risk,
            )
            for r in rows
        ],
    )


@router.get("/patterns/states")
def rank_states(
    db: Session = Depends(get_db), user: User = Depends(current_user),
    flag_threshold: float = Query(50, ge=0, le=100),
    high_threshold: float = Query(70, ge=0, le=100),
) -> dict:
    """Per-state aggregates for the choropleth map (scoped like every other pattern endpoint).

    `flagged` = combined score >= flag_threshold (medium + high, the same definition as the header
    tile); `flagged_pct` is the share of the state's projects. A State user gets only their own
    state; a District / MP user gets the single state their scope sits in, counting ONLY the
    projects inside their scope (see `scope_label`). States are where the WORK is located (work_state),
    so a district user's figures land on their district's state, never on an MP's home state.
    """
    scope, sparams = scope_sql(user, "p")
    rows = db.execute(
        text(
            f"""
            SELECT p.work_state AS state,
                   count(*) AS project_count,
                   avg(rf.combined_risk_score) AS avg_risk,
                   count(*) FILTER (WHERE rf.combined_risk_score >= :flag) AS flagged,
                   count(*) FILTER (WHERE rf.combined_risk_score >= :high) AS high
            FROM projects p
            JOIN risk_flags rf ON rf.project_id = p.id
            WHERE p.work_state IS NOT NULL{scope}
            GROUP BY p.work_state
            ORDER BY 1
            """
        ),
        {"flag": flag_threshold, "high": high_threshold, **sparams},
    ).all()
    # Works whose location could not be resolved (ambiguous district name) have work_state NULL: they are on
    # no state's map and in no State/District scope, but they DO count nationally, so report them here.
    # A scoped user always gets 0 (their scope cannot match a NULL); the Ministry sees the real number.
    unlocated = db.execute(
        text(f"SELECT count(*) FROM projects p JOIN risk_flags rf ON rf.project_id = p.id "
             f"WHERE p.work_state IS NULL{scope}"),
        sparams,
    ).scalar() or 0
    return {
        "scope_label": scope_label(user),
        # national | state | district | mp -- the UI draws a map only where a whole-state colour is accurate
        "scope_kind": {"ministry": "national", "state_nodal": "state",
                       "district_authority": "district", "mp_self": "mp"}[user.role],
        "unlocated_count": int(unlocated),
        "flag_threshold": flag_threshold,
        "high_threshold": high_threshold,
        "items": [
            {
                "state": r.state,
                "project_count": r.project_count,
                "avg_risk_score": round(float(r.avg_risk or 0), 1),
                "flagged_count": r.flagged,
                "flagged_pct": round(100.0 * r.flagged / r.project_count, 1) if r.project_count else 0.0,
                "high_risk_count": r.high,
            }
            for r in rows
        ],
    }


@router.get("/patterns/contractors", response_model=PatternRankList)
def rank_contractors(
    db: Session = Depends(get_db), user: User = Depends(current_user),
    limit: int = Query(20, ge=1, le=100),
) -> PatternRankList:
    uscope, sparams = _unit_scope(user)
    rows = db.execute(
        text(
            f"""
            WITH per AS (
                SELECT vt.mp_name, vt.constituency,
                       COALESCE(NULLIF(vt.vendor, ''), 'UNKNOWN') AS vendor,
                       count(*) AS vc, COALESCE(sum(vt.amount), 0) AS vv
                FROM vendor_transactions vt
                WHERE 1=1{uscope}
                GROUP BY 1, 2, 3
            ),
            unit AS (
                SELECT mp_name, constituency, sum(vc) AS uc, sum(vv) AS uv,
                       count(*) AS nvendors
                FROM per GROUP BY 1, 2
            ),
            j AS (
                SELECT p.vendor, p.vc, p.vv,
                       p.vc::float / NULLIF(u.uc, 0) AS sc,
                       p.vv / NULLIF(u.uv, 0) AS sv,
                       u.uc, u.nvendors
                FROM per p
                JOIN unit u ON u.mp_name = p.mp_name
                          AND u.constituency IS NOT DISTINCT FROM p.constituency
            )
            SELECT vendor,
                   sum(vc) AS total_txn,
                   sum(CASE WHEN nvendors >= 2 AND uc >= :min_unit AND vc >= :min_vendor
                            AND (sc >= :thr OR sv >= :thr) THEN vc ELSE 0 END) AS flagged_txn,
                   max(GREATEST(COALESCE(sc, 0), COALESCE(sv, 0))) AS max_share
            FROM j
            GROUP BY vendor
            HAVING sum(CASE WHEN nvendors >= 2 AND uc >= :min_unit AND vc >= :min_vendor
                            AND (sc >= :thr OR sv >= :thr) THEN vc ELSE 0 END) > 0
            ORDER BY flagged_txn DESC, max_share DESC
            LIMIT :lim
            """
        ),
        {
            "thr": CONTRACTOR_SHARE_THRESHOLD,
            "min_unit": CONTRACTOR_MIN_UNIT_TXNS,
            "min_vendor": CONTRACTOR_MIN_VENDOR_TXNS,
            "lim": limit,
            **sparams,
        },
    ).all()
    return PatternRankList(
        dimension="contractor",
        items=[
            PatternRankRow(
                key=r.vendor,
                txn_count=r.total_txn,
                flagged_txn_count=r.flagged_txn,
                max_share_of_unit_value=round(float(r.max_share or 0), 3),
            )
            for r in rows
        ],
    )


# --------------------------------------------------------------------------- #
# Single-entity drill-in
# --------------------------------------------------------------------------- #
@router.get("/patterns/network")
def contractor_network(
    db: Session = Depends(get_db), user: User = Depends(current_user),
    limit: int = Query(40, ge=1, le=150),
) -> dict:
    """Edges for the contractor-MP network graph: the strongest FLAGGED MP <-> vendor relationships.

    An edge is one (MP unit, vendor) pair that the contractor-concentration rule flags (same thresholds
    and same minimum-volume guards as `rank_contractors` / the rule engine): the vendor holds >= the
    share threshold of that unit's transaction count or value. Ranked by the vendor's share of the
    unit's value, then by value. Scoped like every pattern endpoint (whole units, so shares stay true).
    Only ids/names/aggregates are returned, never any synthetic-data label.
    """
    uscope, sparams = _unit_scope(user)
    rows = db.execute(
        text(
            f"""
            WITH per AS (
                SELECT vt.mp_name, vt.constituency, max(vt.state) AS state,
                       COALESCE(NULLIF(vt.vendor, ''), 'UNKNOWN') AS vendor,
                       count(*) AS vc, COALESCE(sum(vt.amount), 0) AS vv
                FROM vendor_transactions vt
                WHERE 1=1{uscope}
                GROUP BY vt.mp_name, vt.constituency, 4
            ),
            unit AS (
                SELECT mp_name, constituency, sum(vc) AS uc, sum(vv) AS uv, count(*) AS nvendors
                FROM per GROUP BY 1, 2
            )
            SELECT p.mp_name, p.constituency, p.state, p.vendor, p.vc, p.vv,
                   p.vc::float / NULLIF(u.uc, 0) AS sc,
                   p.vv / NULLIF(u.uv, 0) AS sv,
                   u.uc, u.uv
            FROM per p
            JOIN unit u ON u.mp_name = p.mp_name AND u.constituency IS NOT DISTINCT FROM p.constituency
            WHERE u.nvendors >= 2 AND u.uc >= :min_unit AND p.vc >= :min_vendor
              AND (p.vc::float / NULLIF(u.uc, 0) >= :thr OR p.vv / NULLIF(u.uv, 0) >= :thr)
            ORDER BY sv DESC NULLS LAST, p.vv DESC, p.mp_name, p.vendor
            LIMIT :lim
            """
        ),
        {
            "thr": CONTRACTOR_SHARE_THRESHOLD,
            "min_unit": CONTRACTOR_MIN_UNIT_TXNS,
            "min_vendor": CONTRACTOR_MIN_VENDOR_TXNS,
            "lim": limit,
            **sparams,
        },
    ).all()
    return {
        "scope_label": scope_label(user),
        "share_threshold": CONTRACTOR_SHARE_THRESHOLD,
        "edges": [
            {
                "mp_name": r.mp_name, "constituency": r.constituency, "state": r.state,
                "vendor": r.vendor, "txn_count": r.vc, "txn_value": round(float(r.vv), 2),
                "share_of_unit_count": round(float(r.sc or 0), 3),
                "share_of_unit_value": round(float(r.sv or 0), 3),
                "unit_txn_count": r.uc, "unit_txn_value": round(float(r.uv), 2),
            }
            for r in rows
        ],
    }


@router.get("/districts/{district}/pattern", response_model=DistrictPattern)
def district_pattern(
    district: str,
    db: Session = Depends(get_db), user: User = Depends(current_user),
    threshold: float = Query(70, ge=0, le=100),
    state: str | None = Query(None, description="state the district is in (district names repeat across states)"),
) -> DistrictPattern:
    scope, sparams = scope_sql(user, "p")
    st_cond = " AND upper(p.work_state) = upper(:st)" if state else ""
    if state:
        sparams = {**sparams, "st": state}
    summary = db.execute(
        text(
            f"""
            SELECT count(*) AS n,
                   avg(rf.combined_risk_score) AS avg_risk,
                   count(*) FILTER (WHERE rf.combined_risk_score >= :thr) AS high_risk
            FROM projects p
            JOIN risk_flags rf ON rf.project_id = p.id
            WHERE upper(p.district) = upper(:d){st_cond}{scope}
            """
        ),
        {"d": district, "thr": threshold, **sparams},
    ).one()
    if not summary.n:
        raise HTTPException(status_code=404, detail=f"No projects for district {district!r}")

    cats = db.execute(
        text(
            f"""
            SELECT COALESCE(NULLIF(p.derived_category, ''), 'other') AS cat,
                   count(*) AS n,
                   avg(rf.combined_risk_score) AS avg_risk
            FROM projects p
            JOIN risk_flags rf ON rf.project_id = p.id
            WHERE upper(p.district) = upper(:d){st_cond}{scope}
            GROUP BY 1
            ORDER BY n DESC
            """
        ),
        {"d": district, **sparams},
    ).all()

    return DistrictPattern(
        district=district.upper(),
        state=state,
        project_count=summary.n,
        avg_risk_score=round(float(summary.avg_risk or 0), 1),
        high_risk_count=summary.high_risk,
        threshold=threshold,
        categories=[
            DistrictCategoryStat(
                derived_category=c.cat,
                project_count=c.n,
                avg_risk_score=round(float(c.avg_risk or 0), 1),
            )
            for c in cats
        ],
    )


@router.get("/contractors/{vendor}/pattern", response_model=ContractorPattern)
def contractor_pattern(
    vendor: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> ContractorPattern:
    uscope, sparams = _unit_scope(user)
    rows = db.execute(
        text(
            f"""
            WITH units AS (
                SELECT DISTINCT vt.mp_name, vt.constituency
                FROM vendor_transactions vt
                WHERE lower(COALESCE(vt.vendor, '')) = lower(:v){uscope}
            )
            SELECT vt.mp_name, vt.constituency,
                   count(*) FILTER (WHERE lower(COALESCE(vt.vendor, '')) = lower(:v)) AS vc,
                   COALESCE(sum(vt.amount) FILTER (WHERE lower(COALESCE(vt.vendor, '')) = lower(:v)), 0) AS vv,
                   count(*) AS uc,
                   COALESCE(sum(vt.amount), 0) AS uv
            FROM vendor_transactions vt
            JOIN units u ON u.mp_name = vt.mp_name
                        AND u.constituency IS NOT DISTINCT FROM vt.constituency
            GROUP BY vt.mp_name, vt.constituency
            """
        ),
        {"v": vendor, **sparams},
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No transactions for vendor {vendor!r}")

    thr = CONTRACTOR_SHARE_THRESHOLD
    units: list[ContractorUnitShare] = []
    total_c = total_v = flagged_c = 0
    max_share_v = max_share_c = 0.0
    for r in rows:
        sc = (r.vc / r.uc) if r.uc else 0.0
        sv = (float(r.vv) / float(r.uv)) if r.uv else 0.0
        flagged = (
            r.uc >= CONTRACTOR_MIN_UNIT_TXNS
            and r.vc >= CONTRACTOR_MIN_VENDOR_TXNS
            and (sc >= thr or sv >= thr)
        )
        total_c += r.vc
        total_v += float(r.vv)
        max_share_v = max(max_share_v, sv)
        max_share_c = max(max_share_c, sc)
        if flagged:
            flagged_c += r.vc
        units.append(
            ContractorUnitShare(
                mp_name=r.mp_name,
                constituency=r.constituency,
                txn_count=r.vc,
                txn_value=round(float(r.vv), 2),
                share_of_unit_count=round(sc, 3),
                share_of_unit_value=round(sv, 3),
                concentration_flagged=flagged,
            )
        )
    units.sort(key=lambda u: u.share_of_unit_value, reverse=True)

    return ContractorPattern(
        vendor=vendor,
        total_txn_count=total_c,
        total_txn_value=round(total_v, 2),
        flagged_txn_count=flagged_c,
        unit_count=len(units),
        max_share_of_unit_value=round(max_share_v, 3),
        max_share_of_unit_count=round(max_share_c, 3),
        units=units,
    )
