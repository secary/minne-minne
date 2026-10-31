"""Initial ingestion schema and the two configured wiki sources."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url", sa.Text, nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("interval_months", sa.Integer, nullable=False),
        sa.Column("max_pages", sa.Integer, nullable=False),
        sa.Column("max_depth", sa.Integer, nullable=False),
        sa.Column("delay_seconds", sa.Integer, nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "crawl_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=False
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pages_checked", sa.Integer, nullable=False),
        sa.Column("snapshots_created", sa.Integer, nullable=False),
        sa.Column("truncated", sa.Boolean, nullable=False),
        sa.Column("errors", sa.JSON, nullable=False),
        sa.Column("error", sa.Text),
    )
    op.create_index(
        "one_active_crawl_per_source",
        "crawl_jobs",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )
    op.create_table(
        "source_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id", sa.String(36), sa.ForeignKey("sources.id"), nullable=False
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "url"),
    )
    op.create_table(
        "raw_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "page_id", sa.String(36), sa.ForeignKey("source_pages.id"), nullable=False
        ),
        sa.Column(
            "job_id", sa.String(36), sa.ForeignKey("crawl_jobs.id"), nullable=False
        ),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("path", sa.Text, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_modified", sa.Text),
        sa.Column("content_type", sa.Text, nullable=False),
    )
    table = sa.table(
        "sources",
        sa.column("id"),
        sa.column("name"),
        sa.column("url"),
        sa.column("enabled"),
        sa.column("interval_months"),
        sa.column("max_pages"),
        sa.column("max_depth"),
        sa.column("delay_seconds"),
        sa.column("next_run_at"),
    )
    op.bulk_insert(
        table,
        [
            dict(
                id=identifier,
                name=name,
                url=url,
                enabled=True,
                interval_months=1,
                max_pages=1000,
                max_depth=2,
                delay_seconds=3,
                next_run_at=datetime.now(UTC),
            )
            for identifier, name, url in [
                (
                    "wikiwiki-kancolle",
                    "艦これ攻略 Wiki",
                    "https://wikiwiki.jp/kancolle/",
                ),
                (
                    "kcwiki-zh",
                    "舰娘百科",
                    "https://zh.kcwiki.cn/wiki/%E8%88%B0%E5%A8%98%E7%99%BE%E7%A7%91",
                ),
            ]
        ],
    )


def downgrade():
    for name in ("raw_snapshots", "source_pages", "crawl_jobs", "sources"):
        op.drop_table(name)
