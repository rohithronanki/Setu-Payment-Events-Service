from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import logging
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.db.session import Base, engine
    import app.models.models  # noqa: F401 — registers models with Base.metadata
    logger.info("Creating database tables if not exist...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database ready.")
    yield


app = FastAPI(
    title="Setu Payment Events Service",
    description="Payment lifecycle event ingestion and reconciliation service.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_request_timing(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)
    response.headers["X-Response-Time-Ms"] = str(duration_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


from app.api.routes import events, transactions, reconciliation  # noqa: E402
app.include_router(events.router)
app.include_router(transactions.router)
app.include_router(reconciliation.router)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}
