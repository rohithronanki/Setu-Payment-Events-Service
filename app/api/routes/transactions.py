from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.db.session import get_db
from app.schemas.schemas import PaginatedTransactions, TransactionDetail, TransactionStatusEnum
from app.services.transaction_service import list_transactions, get_transaction_detail

router = APIRouter(prefix="/transactions", tags=["Transactions"])


@router.get(
    "",
    response_model=PaginatedTransactions,
    summary="List transactions with optional filters",
)
def get_transactions(
    merchant_id: Optional[str] = Query(None, description="Filter by merchant ID"),
    status: Optional[TransactionStatusEnum] = Query(None, description="Filter by transaction status"),
    date_from: Optional[datetime] = Query(None, description="Filter transactions created on or after this datetime (ISO 8601)"),
    date_to: Optional[datetime] = Query(None, description="Filter transactions created on or before this datetime (ISO 8601)"),
    sort_by: str = Query("created_at", description="Sort field: created_at | updated_at | amount | status"),
    sort_order: str = Query("desc", description="Sort order: asc | desc"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=200, description="Results per page"),
    db: Session = Depends(get_db),
):
    return list_transactions(
        db,
        merchant_id=merchant_id,
        status=status.value if status else None,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{transaction_id}",
    response_model=TransactionDetail,
    summary="Get full details of a single transaction including event history",
)
def get_transaction(transaction_id: str, db: Session = Depends(get_db)):
    result = get_transaction_detail(db, transaction_id)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction '{transaction_id}' not found.",
        )
    return result
