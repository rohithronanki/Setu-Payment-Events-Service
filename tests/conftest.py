"""
conftest.py — runs before any test file is imported.
Creates all tables on the SQLite test engine so they exist
before the app's lifespan or any test fixture runs.
"""
import os

# Point the app at SQLite BEFORE app.db.session is imported anywhere
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine_test = create_engine(
    "sqlite:///./test.db",
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

# Import Base and all models to register them, then create tables
from app.db.session import Base
from app.models.models import Merchant, Transaction, PaymentEvent  # noqa: F401

Base.metadata.drop_all(bind=engine_test)   # clean slate
Base.metadata.create_all(bind=engine_test) # create fresh tables
