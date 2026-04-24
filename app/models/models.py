from sqlalchemy import (
    Column, String, Numeric, DateTime, ForeignKey,
    Index, UniqueConstraint, Enum as SAEnum, Integer
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.db.session import Base


class EventType(str, enum.Enum):
    payment_initiated = "payment_initiated"
    payment_processed = "payment_processed"
    payment_failed = "payment_failed"
    settled = "settled"


class TransactionStatus(str, enum.Enum):
    initiated = "initiated"
    processed = "processed"
    failed = "failed"
    settled = "settled"


class Merchant(Base):
    __tablename__ = "merchants"

    merchant_id = Column(String, primary_key=True)
    merchant_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    transactions = relationship("Transaction", back_populates="merchant")


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True)
    merchant_id = Column(String, ForeignKey("merchants.merchant_id"), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(10), nullable=False, default="INR")
    status = Column(
        SAEnum(TransactionStatus, name="transaction_status"),
        nullable=False,
        default=TransactionStatus.initiated,
    )
    # Settlement tracking
    is_settled = Column(String(5), nullable=False, default="false")  # stored as string for SQLite compat
    settled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)  # timestamp of first event
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    merchant = relationship("Merchant", back_populates="transactions")
    events = relationship("PaymentEvent", back_populates="transaction", order_by="PaymentEvent.timestamp")

    __table_args__ = (
        Index("ix_transactions_merchant_id", "merchant_id"),
        Index("ix_transactions_status", "status"),
        Index("ix_transactions_created_at", "created_at"),
        Index("ix_transactions_merchant_status", "merchant_id", "status"),
    )


class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=False)
    event_type = Column(
        SAEnum(EventType, name="event_type"),
        nullable=False,
    )
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), nullable=False)
    merchant_id = Column(String, nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    currency = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transaction = relationship("Transaction", back_populates="events")

    __table_args__ = (
        # Idempotency: same event_id for same transaction is a duplicate
        UniqueConstraint("event_id", "transaction_id", name="uq_event_id_transaction"),
        Index("ix_events_transaction_id", "transaction_id"),
        Index("ix_events_event_type", "event_type"),
        Index("ix_events_timestamp", "timestamp"),
    )
