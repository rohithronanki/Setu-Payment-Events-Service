from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from enum import Enum


class EventTypeEnum(str, Enum):
    payment_initiated = "payment_initiated"
    payment_processed = "payment_processed"
    payment_failed = "payment_failed"
    settled = "settled"


class TransactionStatusEnum(str, Enum):
    initiated = "initiated"
    processed = "processed"
    failed = "failed"
    settled = "settled"


# ---------- Event Schemas ----------

class EventIngest(BaseModel):
    event_id: str = Field(..., description="Unique identifier for this event")
    event_type: EventTypeEnum
    transaction_id: str
    merchant_id: str
    merchant_name: str
    amount: Decimal = Field(..., gt=0)
    currency: str = Field(default="INR", max_length=10)
    timestamp: datetime

    @field_validator("amount")
    @classmethod
    def round_amount(cls, v):
        return round(v, 2)


class EventResponse(BaseModel):
    id: int
    event_id: str
    event_type: EventTypeEnum
    transaction_id: str
    merchant_id: str
    amount: Decimal
    currency: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class IngestResult(BaseModel):
    status: str  # "created" | "duplicate"
    message: str
    event_id: str
    transaction_id: str


# ---------- Merchant Schemas ----------

class MerchantOut(BaseModel):
    merchant_id: str
    merchant_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- Transaction Schemas ----------

class TransactionOut(BaseModel):
    transaction_id: str
    merchant_id: str
    merchant_name: Optional[str] = None
    amount: Decimal
    currency: str
    status: TransactionStatusEnum
    is_settled: bool
    settled_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TransactionDetail(TransactionOut):
    merchant: Optional[MerchantOut] = None
    events: List[EventResponse] = []

    model_config = {"from_attributes": True}


class PaginatedTransactions(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[TransactionOut]


# ---------- Reconciliation Schemas ----------

class ReconciliationSummaryItem(BaseModel):
    merchant_id: str
    merchant_name: str
    date: str  # YYYY-MM-DD
    status: str
    transaction_count: int
    total_amount: Decimal


class ReconciliationSummaryResponse(BaseModel):
    total: int
    items: List[ReconciliationSummaryItem]


class DiscrepancyType(str, Enum):
    processed_not_settled = "processed_not_settled"
    settled_without_processing = "settled_without_processing"
    settled_after_failure = "settled_after_failure"
    duplicate_settlement = "duplicate_settlement"


class DiscrepancyItem(BaseModel):
    transaction_id: str
    merchant_id: str
    merchant_name: Optional[str]
    amount: Decimal
    currency: str
    current_status: str
    discrepancy_type: DiscrepancyType
    description: str
    event_count: int
    created_at: datetime


class DiscrepancyResponse(BaseModel):
    total: int
    items: List[DiscrepancyItem]
