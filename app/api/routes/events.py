from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.schemas.schemas import EventIngest, IngestResult
from app.services.event_service import ingest_event, bulk_ingest_events

router = APIRouter(prefix="/events", tags=["Events"])


@router.post(
    "",
    response_model=IngestResult,
    status_code=status.HTTP_200_OK,
    summary="Ingest a single payment lifecycle event",
    description=(
        "Accepts a payment lifecycle event and updates transaction state accordingly. "
        "Duplicate submissions (same event_id + transaction_id) are safely ignored."
    ),
)
def ingest_single_event(payload: EventIngest, db: Session = Depends(get_db)):
    return ingest_event(db, payload)


@router.post(
    "/bulk",
    status_code=status.HTTP_200_OK,
    summary="Ingest a batch of events",
    description="Accepts up to 5000 events in a single request. Returns counts of created, duplicate, and errored events.",
)
def ingest_bulk_events(payloads: List[EventIngest], db: Session = Depends(get_db)):
    if len(payloads) > 5000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Batch size cannot exceed 5000 events.",
        )
    return bulk_ingest_events(db, payloads)
