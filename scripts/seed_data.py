#!/usr/bin/env python3
"""
Seed the database from sample_events.json (or any JSON file with the same schema).
Usage:
    python scripts/seed_data.py
    python scripts/seed_data.py --file path/to/events.json --batch-size 500
"""

import json
import argparse
import sys
import os
import time

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal, Base, engine
from app.services.event_service import bulk_ingest_events
from app.schemas.schemas import EventIngest


def seed(file_path: str, batch_size: int = 500):
    print(f"Creating tables if not exist...")
    Base.metadata.create_all(bind=engine)

    print(f"Loading events from {file_path}...")
    with open(file_path) as f:
        raw_events = json.load(f)

    print(f"Total events to ingest: {len(raw_events)}")

    total_created = 0
    total_duplicate = 0
    total_errors = 0

    db = SessionLocal()
    try:
        batches = [raw_events[i : i + batch_size] for i in range(0, len(raw_events), batch_size)]
        start = time.time()

        for batch_num, batch in enumerate(batches, 1):
            payloads = []
            for ev in batch:
                try:
                    payloads.append(EventIngest(**ev))
                except Exception as e:
                    print(f"  [WARN] Skipping malformed event {ev.get('event_id')}: {e}")
                    total_errors += 1

            if payloads:
                result = bulk_ingest_events(db, payloads)
                total_created += result["created"]
                total_duplicate += result["duplicate"]
                total_errors += len(result["errors"])

            elapsed = time.time() - start
            print(
                f"  Batch {batch_num}/{len(batches)} done | "
                f"created={total_created} dup={total_duplicate} err={total_errors} | "
                f"elapsed={elapsed:.1f}s"
            )
    finally:
        db.close()

    print("\n✅ Seeding complete!")
    print(f"   Created:    {total_created}")
    print(f"   Duplicates: {total_duplicate}")
    print(f"   Errors:     {total_errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed payment events into the database")
    parser.add_argument(
        "--file",
        default="sample_events.json",
        help="Path to the JSON events file (default: sample_events.json)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of events per batch (default: 500)",
    )
    args = parser.parse_args()
    seed(args.file, args.batch_size)
