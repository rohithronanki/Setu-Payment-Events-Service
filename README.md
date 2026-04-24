# Setu Payment Events Service

A production-minded payment lifecycle event ingestion and reconciliation service
 built with **FastAPI** and **PostgreSQL**.

**Summary**: Payment lifecycle event ingestion &amp; reconciliation service built with FastAPI + PostgreSQL. Supports idempotent event ingestion, transaction state management via state machine, paginated queries, and SQL-driven reconciliation reports with discrepancy detection. Includes 22 passing tests and Docker setup.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Start (Docker — Recommended)](#quick-start-docker--recommended)
3. [Local Setup (Without Docker)](#local-setup-without-docker)
4. [Loading Sample Data](#loading-sample-data)
5. [Running Tests](#running-tests)
6. [API Documentation](#api-documentation)
7. [Deployment](#deployment)
8. [Schema Design](#schema-design)
9. [Assumptions & Tradeoffs](#assumptions--tradeoffs)
10. [AI Tool Disclosure](#ai-tool-disclosure)

---

## Architecture Overview

```
┌─────────────────────────────────────────┐
│              FastAPI App                │
│                                         │
│  POST /events          ─► Event Service │
│  POST /events/bulk     ─► Event Service │
│  GET  /transactions    ─► Txn Service   │
│  GET  /transactions/:id─► Txn Service   │
│  GET  /reconciliation/summary   ─► Recon│
│  GET  /reconciliation/discrepancies ─►  │
└──────────────┬──────────────────────────┘
               │ SQLAlchemy ORM
               ▼
      ┌─────────────────┐
      │   PostgreSQL     │
      │                  │
      │  merchants       │
      │  transactions    │
      │  payment_events  │
      └─────────────────┘
```

**Key design decisions:**

- **FastAPI** for async-capable, auto-documented REST APIs
- **SQLAlchemy 2.x ORM** for typed, composable queries
- **PostgreSQL** for robust indexing, window functions, and `FILTER` aggregation
 used in reconciliation                                                         - **State machine** in the event service controls valid status transitions — pre
vents invalid state corruption                                                  - **Idempotency** enforced by a `UNIQUE (event_id, transaction_id)` constraint a
t the DB level, plus an application-level pre-check                             - All filtering, sorting, pagination, and aggregation happen **in SQL** — no Pyt
hon loops over result sets                                                      
---

## Quick Start (Docker — Recommended)

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed an
d running                                                                       
### Steps

```bash
# 1. Clone the repo
git clone https://github.com/rohithronanki/Setu-Payment-Events-Service.git
cd Setu-Payment-Events-Service

# 2. Start Postgres + API
docker compose up --build

# 3. In a separate terminal, seed the database
docker compose exec api python scripts/seed_data.py --file sample_events.json

# 4. Open the interactive API docs
open http://localhost:8000/docs
```

That's it. The API is live at **http://localhost:8000**.

---

## Local Setup (Without Docker)

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ running locally

### Steps

```bash
# 1. Clone and enter the project
git clone https://github.com/rohithronanki/Setu-Payment-Events-Service.git
cd Setu-Payment-Events-Service

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and set DATABASE_URL to match your local Postgres credentials
# e.g. DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/setu_payme
nts                                                                             
# 5. Create the database (run once)
psql -U postgres -c "CREATE DATABASE setu_payments;"
psql -U postgres -c "CREATE USER setu WITH PASSWORD 'setu';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE setu_payments TO setu;"

# 6. Start the API (tables are auto-created on startup)
uvicorn app.main:app --reload

# 7. Seed the database
python scripts/seed_data.py --file sample_events.json
```

API is live at **http://localhost:8000**.

---

## Loading Sample Data

The `sample_events.json` file contains ~10,000 events across 5 merchants. The se
ed script ingests them in configurable batches and prints progress.             
```bash
# Default (batches of 500)
python scripts/seed_data.py --file sample_events.json

# Custom batch size
python scripts/seed_data.py --file sample_events.json --batch-size 1000

# Via Docker
docker compose exec api python scripts/seed_data.py --file sample_events.json
```

Expected output:
```
Creating tables if not exist...
Loading events from sample_events.json...
Total events to ingest: 10264
  Batch 1/21 done | created=487 dup=13 err=0 | elapsed=1.2s
  ...
✅ Seeding complete!
   Created:    9800
   Duplicates: 464
   Errors:     0
```

---

## Running Tests

Tests use **SQLite in-memory** — no Postgres required.

```bash
# Install dependencies if not done
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run with coverage
pip install pytest-cov
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## API Documentation

Interactive docs are available at:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

A Postman collection is included: `setu_postman_collection.json`

Import it into Postman and set the `base_url` variable to `http://localhost:8000
`.                                                                              
---

### `POST /events` — Ingest a single event

**Request body:**

```json
{
  "event_id": "b768e3a7-9eb3-4603-b21c-a54cc95661bc",
  "event_type": "payment_initiated",
  "transaction_id": "2f86e94c-239c-4302-9874-75f28e3474ee",
  "merchant_id": "merchant_2",
  "merchant_name": "FreshBasket",
  "amount": 15248.29,
  "currency": "INR",
  "timestamp": "2026-01-08T12:11:58.085567+00:00"
}
```

Valid `event_type` values: `payment_initiated`, `payment_processed`, `payment_fa
iled`, `settled`                                                                
**Response:**

```json
{
  "status": "created",
  "message": "Event ingested successfully.",
  "event_id": "b768e3a7-...",
  "transaction_id": "2f86e94c-..."
}
```

`status` is either `"created"` or `"duplicate"`. Duplicate submissions never cor
rupt state.                                                                     
---

### `POST /events/bulk` — Ingest a batch of events

Accepts a JSON array of up to **5000 events**. Returns aggregate counts.

**Response:**
```json
{
  "created": 487,
  "duplicate": 13,
  "errors": []
}
```

---

### `GET /transactions` — List transactions

**Query parameters:**

| Parameter    | Type     | Description                                       |
|--------------|----------|---------------------------------------------------|
| `merchant_id`| string   | Filter by merchant                                |
| `status`     | string   | `initiated` \| `processed` \| `failed` \| `settled` 
|                                                                               | `date_from`  | datetime | ISO 8601 — filter by created_at ≥               |
| `date_to`    | datetime | ISO 8601 — filter by created_at ≤               |
| `sort_by`    | string   | `created_at` \| `updated_at` \| `amount` \| `status`
 |                                                                              | `sort_order` | string   | `asc` \| `desc` (default: `desc`)               |
| `page`       | int      | Page number, 1-indexed (default: 1)              |
| `page_size`  | int      | Results per page, max 200 (default: 20)          |

**Response:**
```json
{
  "total": 2500,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "transaction_id": "...",
      "merchant_id": "merchant_1",
      "merchant_name": "QuickMart",
      "amount": "9169.41",
      "currency": "INR",
      "status": "settled",
      "is_settled": true,
      "settled_at": "2026-01-08T16:56:16Z",
      "created_at": "2026-01-08T13:09:27Z",
      "updated_at": "2026-01-08T16:56:16Z"
    }
  ]
}
```

---

### `GET /transactions/{transaction_id}` — Transaction detail

Returns full transaction info, merchant details, and complete event history.

**Response:**
```json
{
  "transaction_id": "2f86e94c-...",
  "merchant_id": "merchant_2",
  "merchant_name": "FreshBasket",
  "amount": "15248.29",
  "currency": "INR",
  "status": "failed",
  "is_settled": false,
  "settled_at": null,
  "created_at": "2026-01-08T12:11:58Z",
  "updated_at": "2026-01-08T12:38:58Z",
  "merchant": {
    "merchant_id": "merchant_2",
    "merchant_name": "FreshBasket",
    "created_at": "2026-01-08T12:11:58Z"
  },
  "events": [
    {
      "id": 1,
      "event_id": "b768e3a7-...",
      "event_type": "payment_initiated",
      "transaction_id": "2f86e94c-...",
      "merchant_id": "merchant_2",
      "amount": "15248.29",
      "currency": "INR",
      "timestamp": "2026-01-08T12:11:58Z"
    },
    {
      "id": 3,
      "event_id": "da46895f-...",
      "event_type": "payment_failed",
      ...
    }
  ]
}
```

Returns **HTTP 404** if the transaction is not found.

---

### `GET /reconciliation/summary` — Summary report

**Query parameters:** `merchant_id`, `date_from`, `date_to` (all optional)

**Response:**
```json
{
  "total": 42,
  "items": [
    {
      "merchant_id": "merchant_1",
      "merchant_name": "QuickMart",
      "date": "2026-01-08",
      "status": "settled",
      "transaction_count": 12,
      "total_amount": "145832.50"
    }
  ]
}
```

---

### `GET /reconciliation/discrepancies` — Discrepancy report

**Query parameters:** `merchant_id` (optional)

Detects four discrepancy types:

| Type | Description |
|------|-------------|
| `processed_not_settled` | Payment processed but no settlement after 24 hours |
| `settled_without_processing` | Settled with no `payment_processed` event |
| `settled_after_failure` | Settlement recorded despite a failed event |
| `duplicate_settlement` | More than one `settled` event for the same transactio
n |                                                                             
**Response:**
```json
{
  "total": 87,
  "items": [
    {
      "transaction_id": "...",
      "merchant_id": "merchant_4",
      "merchant_name": "TechBazaar",
      "amount": "7954.12",
      "currency": "INR",
      "current_status": "settled",
      "discrepancy_type": "duplicate_settlement",
      "description": "Multiple settlement events recorded for the same transacti
on",                                                                                  "event_count": 4,
      "created_at": "2026-04-08T05:59:24Z"
    }
  ]
}
```

---

## Deployment

### Option A: Render (recommended for free tier)

1. Push your repo to GitHub
2. Create a new **Web Service** on [Render](https://render.com)
3. Set build command: `pip install -r requirements.txt`
4. Set start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add a **PostgreSQL** database on Render and copy the internal connection stri
ng to the `DATABASE_URL` environment variable                                   6. After deploy, seed data: `python scripts/seed_data.py --file sample_events.js
on`                                                                             
### Option B: Railway

1. Push repo to GitHub
2. Create a new project on [Railway](https://railway.app)
3. Add a **PostgreSQL** plugin
4. Set `DATABASE_URL` from the plugin's connection string
5. Deploy — Railway auto-detects Python and runs the Dockerfile

### Option C: Fly.io

```bash
fly launch
fly postgres create
fly secrets set DATABASE_URL=<postgres-connection-string>
fly deploy
```

---

## Schema Design

### `merchants`
| Column | Type | Notes |
|--------|------|-------|
| `merchant_id` | VARCHAR (PK) | Natural key from events |
| `merchant_name` | VARCHAR | |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

### `transactions`
| Column | Type | Notes |
|--------|------|-------|
| `transaction_id` | VARCHAR (PK) | Natural key from events |
| `merchant_id` | VARCHAR (FK) | |
| `amount` | NUMERIC(14,2) | |
| `currency` | VARCHAR(10) | |
| `status` | ENUM | `initiated \| processed \| failed \| settled` |
| `is_settled` | VARCHAR | Tracks settlement independently of status |
| `settled_at` | TIMESTAMPTZ | Nullable |
| `created_at` | TIMESTAMPTZ | Timestamp of the first event |
| `updated_at` | TIMESTAMPTZ | |

**Indexes:** `merchant_id`, `status`, `created_at`, `(merchant_id, status)`

### `payment_events`
| Column | Type | Notes |
|--------|------|-------|
| `id` | SERIAL (PK) | Surrogate key for ordering |
| `event_id` | VARCHAR | |
| `event_type` | ENUM | |
| `transaction_id` | VARCHAR (FK) | |
| `merchant_id` | VARCHAR | Denormalized for fast per-merchant event queries |
| `amount` | NUMERIC(14,2) | |
| `currency` | VARCHAR(10) | |
| `timestamp` | TIMESTAMPTZ | |

**Unique constraint:** `(event_id, transaction_id)` — primary idempotency guard 
                                                                                **Indexes:** `transaction_id`, `event_type`, `timestamp`

---

## Assumptions & Tradeoffs

**State machine strictness**
The service enforces `initiated → processed → settled` and `initiated → failed` 
as the only valid paths. Out-of-order or late-arriving events are still stored in `payment_events` for auditability, but they do not update the transaction's `status`. This means the event log is always complete even when the status reflects the last valid transition.                                                    
**`is_settled` is tracked separately from `status`**
A transaction can be `status=failed` but `is_settled=true` if a settlement event
 arrives after failure (a real discrepancy scenario). Keeping these separate allows reconciliation queries to detect this cleanly without complex joins.        
**Idempotency at two layers**
First, the service queries for the event before inserting. Second, the DB-level 
unique constraint catches any race condition between concurrent requests. The DB constraint is the authoritative guard.                                         
**Bulk ingest runs event-by-event**
The bulk endpoint loops through events individually to preserve the state machin
e logic per transaction. A pure SQL `INSERT ... ON CONFLICT DO NOTHING` bulk approach would be faster but would bypass state transition validation.             
**SQLite for tests, Postgres for production**
Tests use SQLite in-memory for speed and zero setup. The `INTERVAL '24 hours'` s
yntax in the discrepancy query is Postgres-specific, so discrepancy tests are validated against the real schema in integration scenarios.                       
**`merchant_id` denormalized into `payment_events`**
This avoids a join when querying events for a specific merchant and mirrors the 
structure of the incoming event payload.                                        
**No auth/API keys**
Out of scope for this assignment. In production, you'd add OAuth2 or API key mid
dleware.                                                                        
---


