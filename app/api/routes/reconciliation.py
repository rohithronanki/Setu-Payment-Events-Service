from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.db.session import get_db
from app.schemas.schemas import ReconciliationSummaryResponse, DiscrepancyResponse
from app.services.reconciliation_service import (
    get_reconciliation_summary,
    get_reconciliation_discrepancies,
)

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.get(
    "/summary",
    response_model=ReconciliationSummaryResponse,
    summary="Get reconciliation summary grouped by merchant, date, and status",
)
def reconciliation_summary(
    merchant_id: Optional[str] = Query(None, description="Filter by merchant ID"),
    date_from: Optional[datetime] = Query(None, description="Start of date range (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="End of date range (ISO 8601)"),
    db: Session = Depends(get_db),
):
    return get_reconciliation_summary(db, merchant_id=merchant_id, date_from=date_from, date_to=date_to)


@router.get(
    "/discrepancies",
    response_model=DiscrepancyResponse,
    summary="List transactions with payment/settlement inconsistencies",
    description=(
        "Returns transactions where the payment and settlement states are inconsistent:\n"
        "- `processed_not_settled`: processed but not settled after 24h\n"
        "- `settled_without_processing`: settled with no payment_processed event\n"
        "- `settled_after_failure`: settled despite being marked failed\n"
        "- `duplicate_settlement`: more than one settled event recorded\n"
    ),
)
def reconciliation_discrepancies(
    merchant_id: Optional[str] = Query(None, description="Filter by merchant ID"),
    db: Session = Depends(get_db),
):
    return get_reconciliation_discrepancies(db, merchant_id=merchant_id)
