from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import datetime
from decimal import Decimal

from app.schemas.schemas import (
    ReconciliationSummaryResponse,
    ReconciliationSummaryItem,
    DiscrepancyResponse,
    DiscrepancyItem,
    DiscrepancyType,
)


def _dialect(db: Session) -> str:
    return db.get_bind().dialect.name


def _24h_ago(db: Session) -> str:
    if _dialect(db) == "sqlite":
        return "datetime('now', '-24 hours')"
    return "NOW() - INTERVAL '24 hours'"


def get_reconciliation_summary(
    db: Session,
    merchant_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    group_by: str = "merchant_date_status",
) -> ReconciliationSummaryResponse:
    filters = []
    params = {}

    if merchant_id:
        filters.append("t.merchant_id = :merchant_id")
        params["merchant_id"] = merchant_id
    if date_from:
        filters.append("t.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("t.created_at <= :date_to")
        params["date_to"] = date_to

    where_clause = ("WHERE " + " AND ".join(filters)) if filters else ""

    sql = f"""
        SELECT
            t.merchant_id,
            m.merchant_name,
            DATE(t.created_at) AS txn_date,
            t.status,
            COUNT(*)            AS transaction_count,
            SUM(t.amount)       AS total_amount
        FROM transactions t
        JOIN merchants m ON m.merchant_id = t.merchant_id
        {where_clause}
        GROUP BY t.merchant_id, m.merchant_name, DATE(t.created_at), t.status
        ORDER BY txn_date DESC, t.merchant_id, t.status
    """

    rows = db.execute(text(sql), params).fetchall()
    items = [
        ReconciliationSummaryItem(
            merchant_id=r.merchant_id,
            merchant_name=r.merchant_name,
            date=str(r.txn_date),
            status=r.status,
            transaction_count=r.transaction_count,
            total_amount=Decimal(str(r.total_amount)),
        )
        for r in rows
    ]
    return ReconciliationSummaryResponse(total=len(items), items=items)


def get_reconciliation_discrepancies(
    db: Session,
    merchant_id: Optional[str] = None,
) -> DiscrepancyResponse:
    params = {}
    merchant_filter = ""
    if merchant_id:
        merchant_filter = "AND t.merchant_id = :merchant_id"
        params["merchant_id"] = merchant_id

    cutoff = _24h_ago(db)

    sql = f"""
    WITH event_counts AS (
        SELECT
            transaction_id,
            COUNT(*) FILTER (WHERE event_type = 'payment_processed') AS processed_count,
            COUNT(*) FILTER (WHERE event_type = 'payment_failed')    AS failed_count,
            COUNT(*) FILTER (WHERE event_type = 'settled')           AS settled_count,
            MAX(CASE WHEN event_type = 'payment_processed' THEN timestamp END) AS last_processed_at
        FROM payment_events
        GROUP BY transaction_id
    )
    SELECT
        t.transaction_id,
        t.merchant_id,
        m.merchant_name,
        t.amount,
        t.currency,
        t.status,
        ec.processed_count,
        ec.failed_count,
        ec.settled_count,
        t.created_at,
        CASE
            WHEN ec.settled_count > 1
                THEN 'duplicate_settlement'
            WHEN ec.failed_count > 0 AND ec.settled_count > 0
                THEN 'settled_after_failure'
            WHEN ec.processed_count > 0 AND ec.settled_count = 0
                AND ec.last_processed_at < {cutoff}
                THEN 'processed_not_settled'
            WHEN ec.settled_count > 0 AND ec.processed_count = 0
                THEN 'settled_without_processing'
        END AS discrepancy_type
    FROM transactions t
    JOIN merchants m ON m.merchant_id = t.merchant_id
    JOIN event_counts ec ON ec.transaction_id = t.transaction_id
    WHERE (
        ec.settled_count > 1
        OR (ec.failed_count > 0 AND ec.settled_count > 0)
        OR (ec.processed_count > 0 AND ec.settled_count = 0
            AND ec.last_processed_at < {cutoff})
        OR (ec.settled_count > 0 AND ec.processed_count = 0)
    )
    {merchant_filter}
    ORDER BY t.created_at DESC
    """

    rows = db.execute(text(sql), params).fetchall()

    ec_map = {
        r.transaction_id: r.cnt
        for r in db.execute(text(
            "SELECT transaction_id, COUNT(*) AS cnt FROM payment_events GROUP BY transaction_id"
        )).fetchall()
    }

    descriptions = {
        "duplicate_settlement": "Multiple settlement events recorded for the same transaction",
        "settled_after_failure": "Transaction was settled despite having a failed payment event",
        "processed_not_settled": "Payment was processed but no settlement recorded after 24 hours",
        "settled_without_processing": "Settlement recorded with no corresponding payment_processed event",
    }

    items = []
    for r in rows:
        dtype = r.discrepancy_type
        if not dtype:
            continue
        items.append(DiscrepancyItem(
            transaction_id=r.transaction_id,
            merchant_id=r.merchant_id,
            merchant_name=r.merchant_name,
            amount=Decimal(str(r.amount)),
            currency=r.currency,
            current_status=r.status,
            discrepancy_type=DiscrepancyType(dtype),
            description=descriptions.get(dtype, dtype),
            event_count=ec_map.get(r.transaction_id, 0),
            created_at=r.created_at,
        ))

    return DiscrepancyResponse(total=len(items), items=items)
