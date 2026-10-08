"""Restart-safe catalog worker: python -m app.catalog_worker [--once]."""

import argparse
from datetime import datetime, timedelta
import time
from uuid import uuid4

from sqlalchemy import and_, or_, select, update

from app.db import Base, SessionLocal, engine
from app.oncometra_models import CatalogJob
from app.platform_services import upsert_discovery
from app.catalog_connectors import fetch_catalog


def run_once(fetch=fetch_catalog):
    now, token = datetime.utcnow(), str(uuid4())
    eligible = or_(CatalogJob.status == "queued", and_(CatalogJob.status == "running", CatalogJob.lease_until < now))
    with SessionLocal() as db:
        job = db.scalar(select(CatalogJob).where(eligible).order_by(CatalogJob.created_at).limit(1))
        if not job:
            return False
        job_id, registry = job.id, job.registry
        claim = db.execute(update(CatalogJob).where(CatalogJob.id == job_id, eligible).values(
            status="running", lease_token=token, lease_until=now + timedelta(minutes=5),
            attempts=CatalogJob.attempts + 1, error=None))
        db.commit()
        if claim.rowcount != 1:
            return False
    try:
        records = fetch(registry)
        with SessionLocal() as db:
            # Acquire the job row before publishing. An expired worker cannot overwrite its successor.
            owned = db.execute(update(CatalogJob).where(CatalogJob.id == job_id,
                CatalogJob.lease_token == token, CatalogJob.status == "running").values(lease_token=token))
            if owned.rowcount != 1:
                db.rollback()
                return True
            created = sum(upsert_discovery(db, record)[1] for record in records)
            db.execute(update(CatalogJob).where(CatalogJob.id == job_id).values(
                status="succeeded", result={"seen": len(records), "created": created, "refreshed": len(records) - created},
                finished_at=datetime.utcnow(), lease_until=None))
            db.commit()
    except Exception as error:
        with SessionLocal() as db:
            db.execute(update(CatalogJob).where(CatalogJob.id == job_id, CatalogJob.lease_token == token).values(
                status="failed", error=str(error)[:500], finished_at=datetime.utcnow(), lease_until=None))
            db.commit()
    return True


def loop(stop=None):
    while stop is None or not stop.is_set():
        try:
            worked = run_once()
        except Exception:
            # Transient database failures leave the persisted job available after lease expiry.
            worked = False
        if not worked:
            if stop is None:
                time.sleep(2)
            else:
                stop.wait(2)


if __name__ == "__main__":
    from app import models  # Register the existing studies referenced by workspace tables.
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    Base.metadata.create_all(engine)
    run_once() if args.once else loop()
