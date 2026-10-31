from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.app.db.models import Job, Snapshot, Source, now
from backend.app.db.session import Session
from backend.app.ingestion.policy import next_month
from backend.app.worker.main import enqueue

app = FastAPI(title="Minne-Minne ingestion")


class SourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    interval_months: int | None = Field(default=None, ge=1, le=120)
    max_pages: int | None = Field(default=None, ge=1, le=100000)
    max_depth: int | None = Field(default=None, ge=0, le=20)
    delay_seconds: int | None = Field(default=None, ge=1, le=3600)


@app.get("/sources")
def sources():
    with Session() as session:
        return session.scalars(select(Source).order_by(Source.name)).all()


@app.patch("/sources/{source_id}")
def update_source(source_id: str, patch: SourcePatch):
    with Session.begin() as session:
        source = session.scalar(
            select(Source).where(Source.id == source_id).with_for_update()
        )
        if not source:
            raise HTTPException(404, "Source not found")
        values = patch.model_dump(exclude_unset=True)
        if any(value is None for value in values.values()):
            raise HTTPException(422, "Explicit null values are not allowed")
        for key, value in values.items():
            setattr(source, key, value)
        if "interval_months" in values:
            source.next_run_at = next_month(now(), source.interval_months)
        return source


@app.post("/sources/{source_id}/crawl", status_code=202)
def trigger(source_id: str):
    with Session.begin() as session:
        source = session.scalar(
            select(Source).where(Source.id == source_id).with_for_update()
        )
        if not source:
            raise HTTPException(404, "Source not found")
        return enqueue(session, source)


@app.get("/jobs")
def jobs(limit: int = 50):
    with Session() as session:
        return session.scalars(
            select(Job).order_by(Job.created_at.desc()).limit(max(1, min(limit, 200)))
        ).all()


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with Session() as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job


@app.get("/snapshots")
def snapshots(limit: int = 50):
    with Session() as session:
        return session.scalars(
            select(Snapshot)
            .order_by(Snapshot.fetched_at.desc())
            .limit(max(1, min(limit, 200)))
        ).all()
