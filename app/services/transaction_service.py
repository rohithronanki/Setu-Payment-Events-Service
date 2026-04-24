from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select, func, and_
from typing import Optional
from datetime import datetime

from app.models.models import Transaction, Merchant, PaymentEvent
from app.schemas.schemas import PaginatedTransactions, TransactionOut, TransactionDetail


def list_transactions(
    db: Session,
    merchant_id: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> PaginatedTransactions:
    # Allowed sort columns (whitelist to prevent injection)
    allowed_sort = {"created_at", "updated_at", "amount", "status"}
    if sort_by not in allowed_sort:
        sort_by = "created_at"

    filters = []
    if merchant_id:
        filters.append(Transaction.merchant_id == merchant_id)
    if status:
        filters.append(Transaction.status == status)
    if date_from:
        filters.append(Transaction.created_at >= date_from)
    if date_to:
        filters.append(Transaction.created_at <= date_to)

    base_q = select(Transaction).join(Merchant, Transaction.merchant_id == Merchant.merchant_id)
    if filters:
        base_q = base_q.where(and_(*filters))

    # Count query
    count_q = select(func.count()).select_from(base_q.subquery())
    total = db.execute(count_q).scalar_one()

    # Sort
    col = getattr(Transaction, sort_by)
    if sort_order == "asc":
        base_q = base_q.order_by(col.asc())
    else:
        base_q = base_q.order_by(col.desc())

    # Pagination
    offset = (page - 1) * page_size
    base_q = base_q.options(joinedload(Transaction.merchant)).offset(offset).limit(page_size)

    rows = db.execute(base_q).unique().scalars().all()

    items = []
    for txn in rows:
        items.append(
            TransactionOut(
                transaction_id=txn.transaction_id,
                merchant_id=txn.merchant_id,
                merchant_name=txn.merchant.merchant_name if txn.merchant else None,
                amount=txn.amount,
                currency=txn.currency,
                status=txn.status,
                is_settled=txn.is_settled == "true",
                settled_at=txn.settled_at,
                created_at=txn.created_at,
                updated_at=txn.updated_at,
            )
        )

    return PaginatedTransactions(total=total, page=page, page_size=page_size, items=items)


def get_transaction_detail(db: Session, transaction_id: str) -> Optional[TransactionDetail]:
    txn = db.execute(
        select(Transaction)
        .options(
            joinedload(Transaction.merchant),
            joinedload(Transaction.events),
        )
        .where(Transaction.transaction_id == transaction_id)
    ).unique().scalar_one_or_none()

    if not txn:
        return None

    from app.schemas.schemas import MerchantOut, EventResponse

    merchant_out = None
    if txn.merchant:
        merchant_out = MerchantOut(
            merchant_id=txn.merchant.merchant_id,
            merchant_name=txn.merchant.merchant_name,
            created_at=txn.merchant.created_at,
        )

    events_out = [
        EventResponse(
            id=e.id,
            event_id=e.event_id,
            event_type=e.event_type,
            transaction_id=e.transaction_id,
            merchant_id=e.merchant_id,
            amount=e.amount,
            currency=e.currency,
            timestamp=e.timestamp,
        )
        for e in txn.events
    ]

    return TransactionDetail(
        transaction_id=txn.transaction_id,
        merchant_id=txn.merchant_id,
        merchant_name=txn.merchant.merchant_name if txn.merchant else None,
        amount=txn.amount,
        currency=txn.currency,
        status=txn.status,
        is_settled=txn.is_settled == "true",
        settled_at=txn.settled_at,
        created_at=txn.created_at,
        updated_at=txn.updated_at,
        merchant=merchant_out,
        events=events_out,
    )
