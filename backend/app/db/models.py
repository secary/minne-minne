from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_months: Mapped[int] = mapped_column(Integer, default=1)
    max_pages: Mapped[int] = mapped_column(Integer, default=1000)
    max_depth: Mapped[int] = mapped_column(Integer, default=2)
    delay_seconds: Mapped[int] = mapped_column(Integer, default=3)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "crawl_jobs"
    __table_args__ = (
        Index(
            "one_active_crawl_per_source",
            "source_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    pages_checked: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class Page(Base):
    __tablename__ = "source_pages"
    __table_args__ = (UniqueConstraint("source_id", "url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    url: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Snapshot(Base):
    __tablename__ = "raw_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    page_id: Mapped[str] = mapped_column(ForeignKey("source_pages.id"))
    job_id: Mapped[str] = mapped_column(ForeignKey("crawl_jobs.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_modified: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
