"""District- and contractor-level aggregation for the pattern view.

All queries select explicit columns -- `is_synthetic_anomaly` / `anomaly_type`
are never referenced here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
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


# --------------------------------------------------------------------------- #
# Cross-entity rankings (for the pattern-view charts)
# --------------------------------------------------------------------------- #
@router.get("/patterns/districts", response_model=PatternRankList)
def rank_districts(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    threshold: float = Query(70, ge=0, le=100),
) -> PatternRankList:
    rows = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(p.district, ''), '(unknown)') AS key,
                   count(*) AS project_count,
                   avg(rf.combined_risk_score) AS avg_risk,
                   count(*) FILTER (WHERE rf.combined_risk_score >= :thr) AS high_risk
            FROM projects p
            JOIN risk_flags rf ON rf.project_id = p.id
            GROUP BY 1
            ORDER BY high_risk DESC, avg_risk DESC
            LIMIT :lim
            """
        ),
        {"thr": threshold, "lim": limit},
    ).all()
    return PatternRankList(
        dimension="district",
        items=[
            PatternRankRow(
                key=r.key,
                project_count=r.project_count,
                avg_risk_score=round(float(r.avg_risk or 0), 1),
                high_risk_count=r.high_risk,
            )
            for r in rows
        ],
    )


@router.get("/patterns/contractors", response_model=PatternRankList)
def rank_contractors(
    db: Session = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> PatternRankList:
    rows = db.execute(
        text(
            """
            WITH per AS (
                SELECT mp_name, constituency, COALESCE(NULLIF(vendor, ''), 'UNKNOWN') AS vendor,
                       count(*) AS vc, COALESCE(sum(amount), 0) AS vv
                FROM vendor_transactions
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
@router.get("/districts/{district}/pattern", response_model=DistrictPattern)
def district_pattern(
    district: str,
    db: Session = Depends(get_db),
    threshold: float = Query(70, ge=0, le=100),
) -> DistrictPattern:
    summary = db.execute(
        text(
            """
            SELECT count(*) AS n,
                   avg(rf.combined_risk_score) AS avg_risk,
                   count(*) FILTER (WHERE rf.combined_risk_score >= :thr) AS high_risk
            FROM projects p
            JOIN risk_flags rf ON rf.project_id = p.id
            WHERE upper(p.district) = upper(:d)
            """
        ),
        {"d": district, "thr": threshold},
    ).one()
    if not summary.n:
        raise HTTPException(status_code=404, detail=f"No projects for district {district!r}")

    cats = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(p.derived_category, ''), 'other') AS cat,
                   count(*) AS n,
                   avg(rf.combined_risk_score) AS avg_risk
            FROM projects p
            JOIN risk_flags rf ON rf.project_id = p.id
            WHERE upper(p.district) = upper(:d)
            GROUP BY 1
            ORDER BY n DESC
            """
        ),
        {"d": district},
    ).all()

    return DistrictPattern(
        district=district.upper(),
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
def contractor_pattern(vendor: str, db: Session = Depends(get_db)) -> ContractorPattern:
    rows = db.execute(
        text(
            """
            WITH units AS (
                SELECT DISTINCT mp_name, constituency
                FROM vendor_transactions
                WHERE lower(COALESCE(vendor, '')) = lower(:v)
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
        {"v": vendor},
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
