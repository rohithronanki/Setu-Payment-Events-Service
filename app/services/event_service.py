from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from typing import List

from app.models.models import PaymentEvent, Transaction, Merchant, TransactionStatus, EventType
from app.schemas.schemas import EventIngest, IngestResult


# Valid state transitions: current_status -> allowed next event types
VALID_TRANSITIONS = {
    TransactionStatus.initiated: {EventType.payment_processed, EventType.payment_failed},
    TransactionStatus.processed: {EventType.settled},
    TransactionStatus.failed: set(),   # terminal
    TransactionStatus.settled: set(),  # terminal
}

STATUS_FROM_EVENT = {
    EventType.payment_initiated: TransactionStatus.initiated,
    EventType.payment_processed: TransactionStatus.processed,
    EventType.payment_failed: TransactionStatus.failed,
    EventType.settled: TransactionStatus.settled,
}


def ingest_event(db: Session, payload: EventIngest) -> IngestResult:
    """
    Ingest a single payment event.
    - Idempotent: duplicate (event_id, transaction_id) pairs are silently skipped.
    - Upserts merchant on first seen.
    - Creates transaction on first event, updates status on subsequent events.
    - State machine: only allows forward transitions; out-of-order events are stored
      but do not corrupt transaction status.
    """
    # 1. Check for duplicate event (idempotency)
    existing = db.execute(
        select(PaymentEvent).where(
            PaymentEvent.event_id == payload.event_id,
            PaymentEvent.transaction_id == payload.transaction_id,
        )
    ).scalar_one_or_none()

    if existing:
        return IngestResult(
            status="duplicate",
            message="Event already ingested; no state change applied.",
            event_id=payload.event_id,
            transaction_id=payload.transaction_id,
        )

    # 2. Upsert merchant
    merchant = db.get(Merchant, payload.merchant_id)
    if not merchant:
        merchant = Merchant(
            merchant_id=payload.merchant_id,
            merchant_name=payload.merchant_name,
        )
        db.add(merchant)
    else:
        # Update name in case it changed
        merchant.merchant_name = payload.merchant_name

    # 3. Get or create transaction
    txn = db.get(Transaction, payload.transaction_id)

    if not txn:
        if payload.event_type != EventType.payment_initiated:
            # Allow creating transaction even for out-of-order first events (data resilience)
            pass
        txn = Transaction(
            transaction_id=payload.transaction_id,
            merchant_id=payload.merchant_id,
            amount=payload.amount,
            currency=payload.currency,
            status=STATUS_FROM_EVENT[payload.event_type],
            is_settled="true" if payload.event_type == EventType.settled else "false",
            settled_at=payload.timestamp if payload.event_type == EventType.settled else None,
            created_at=payload.timestamp,
        )
        db.add(txn)
    else:
        # Apply state transition if valid
        new_status = STATUS_FROM_EVENT[payload.event_type]
        current_status = txn.status

        allowed_events = VALID_TRANSITIONS.get(current_status, set())
        if payload.event_type in allowed_events:
            txn.status = new_status

        # Track settlement separately (even if status is not updated)
        if payload.event_type == EventType.settled and txn.is_settled == "false":
            txn.is_settled = "true"
            txn.settled_at = payload.timestamp

    # 4. Record the event
    event = PaymentEvent(
        event_id=payload.event_id,
        event_type=payload.event_type,
        transaction_id=payload.transaction_id,
        merchant_id=payload.merchant_id,
        amount=payload.amount,
        currency=payload.currency,
        timestamp=payload.timestamp,
    )
    db.add(event)

    try:
        db.commit()
    except IntegrityError:
        # Race condition: another process inserted same event_id concurrently
        db.rollback()
        return IngestResult(
            status="duplicate",
            message="Concurrent duplicate event detected; no state change applied.",
            event_id=payload.event_id,
            transaction_id=payload.transaction_id,
        )

    return IngestResult(
        status="created",
        message="Event ingested successfully.",
        event_id=payload.event_id,
        transaction_id=payload.transaction_id,
    )


def bulk_ingest_events(db: Session, payloads: List[EventIngest]) -> dict:
    """Ingest a list of events, returning per-item results."""
    results = {"created": 0, "duplicate": 0, "errors": []}
    for payload in payloads:
        try:
            result = ingest_event(db, payload)
            if result.status == "created":
                results["created"] += 1
            else:
                results["duplicate"] += 1
        except Exception as e:
            db.rollback()
            results["errors"].append({"event_id": payload.event_id, "error": str(e)})
    return results
