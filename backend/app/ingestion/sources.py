from dataclasses import asdict

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from backend.app.config import CRAWL_SOURCES
from backend.app.db.models import Source, now
from backend.app.db.session import Session
from backend.app.ingestion.policy import normalize


def sync_sources():
    """Register configured sources without overwriting runtime crawl settings."""
    records = []
    for source in CRAWL_SOURCES:
        url = normalize(source.url, source.url)
        if not url:
            raise ValueError(
                f"Source URL is outside configured wiki scope: {source.id}"
            )
        record = asdict(source)
        record.pop("root_path")
        records.append(record | {"url": url, "next_run_at": now()})
    with Session.begin() as session:
        session.execute(
            update(Source)
            .where(Source.id.not_in([source.id for source in CRAWL_SOURCES]))
            .values(enabled=False)
        )
        if records:
            statement = insert(Source).values(records)
            statement = statement.on_conflict_do_update(
                index_elements=[Source.id],
                set_={"name": statement.excluded.name, "url": statement.excluded.url},
            )
            session.execute(statement)
