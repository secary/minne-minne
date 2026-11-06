import argparse
import logging
import time
from datetime import timedelta

from sqlalchemy import select, text

from backend.app.config import settings
from backend.app.db.models import Job, Source, now
from backend.app.db.session import Session, engine
from backend.app.ingestion.policy import next_month
from backend.app.ingestion.sources import sync_sources
from backend.app.worker.crawl import crawl

logger = logging.getLogger(__name__)


def enqueue(session, source):
    active = session.scalar(
        select(Job).where(
            Job.source_id == source.id, Job.status.in_(["pending", "running"])
        )
    )
    if active:
        return active
    job = Job(source_id=source.id)
    session.add(job)
    session.flush()
    return job


def schedule():
    scheduled_at = now()
    with Session.begin() as session:
        sources = session.scalars(
            select(Source)
            .where(Source.enabled.is_(True), Source.next_run_at <= scheduled_at)
            .with_for_update()
        ).all()
        for source in sources:
            enqueue(session, source)
            source.next_run_at = next_month(scheduled_at, source.interval_months)


def claim(cutoff=None):
    cutoff = cutoff if cutoff is not None else now()
    with Session.begin() as session:
        job = session.scalar(
            select(Job)
            .where(
                Job.status == "pending",
                Job.available_at <= cutoff,
                Job.created_at <= cutoff,
            )
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return
        job.status = "running"
        job.attempts += 1
        job.started_at = now()
        job.pages_checked = job.snapshots_created = 0
        job.errors = []
        job.error = None
        job.truncated = False
        return job.id


def execute(job_id):
    error = None
    try:
        crawl(job_id)
    except Exception as exc:
        logger.exception("Crawl %s failed", job_id)
        error = str(exc)[:1000]
    with Session.begin() as session:
        job = session.get(Job, job_id)
        job.error = error
        if error and job.attempts < 3:
            job.status = "pending"
            job.available_at = now() + timedelta(minutes=5 * job.attempts)
        else:
            job.status = "failed" if error else "succeeded"
            job.finished_at = now()


def tick():
    schedule()
    job_id = claim()
    if job_id is not None:
        execute(job_id)


def run_once(lock):
    lock.execute(text("SELECT 1"))
    schedule()
    # Include freshly scheduled jobs, then freeze eligibility for the whole round.
    cutoff = now()
    processed = 0
    logger.info("Starting crawler round")
    while True:
        # Fail closed if the advisory-lock connection has been lost.
        lock.execute(text("SELECT 1"))
        job_id = claim(cutoff)
        if job_id is None:
            logger.info("Crawler round finished; processed %s job(s)", processed)
            return
        execute(job_id)
        processed += 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the source ingestion worker")
    parser.add_argument(
        "--once", action="store_true", help="Process one round of ready jobs, then exit"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    # One dedicated connection holds the lock across per-page commits.
    with engine.connect() as lock:
        if not lock.scalar(text("SELECT pg_try_advisory_lock(67432109)")):
            raise RuntimeError("Another ingestion worker is already running")
        lock.commit()
        sync_sources()
        with Session.begin() as session:
            for job in session.scalars(select(Job).where(Job.status == "running")):
                job.error = "Worker interrupted"
                job.status = "pending" if job.attempts < 3 else "failed"
                job.available_at = now()
                if job.status == "failed":
                    job.finished_at = now()
        if args.once:
            run_once(lock)
            return
        while True:
            # Fail closed if the advisory-lock connection has been lost.
            lock.execute(text("SELECT 1"))
            tick()
            time.sleep(settings.poll_seconds)


if __name__ == "__main__":
    main()
