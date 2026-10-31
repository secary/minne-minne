from collections import deque

from sqlalchemy import select

from backend.app.config import settings
from backend.app.db.models import Job, Page, Snapshot, Source, now
from backend.app.db.session import Session
from backend.app.ingestion.http import Fetcher
from backend.app.ingestion.policy import Links
from backend.app.ingestion.storage import digest, save


def crawl(job_id: str):
    with Session() as session:
        job = session.get(Job, job_id)
        source = session.get(Source, job.source_id)
        source_id, seed = source.id, source.url
        max_pages, max_depth = source.max_pages, source.max_depth
        fetcher = Fetcher(settings.user_agent, source.delay_seconds)
    queue = deque([(seed, 0)])
    seen = {seed}
    checked = created = 0
    errors = []
    truncated = False
    try:
        fetcher.load_robots(seed)
        while queue and checked < max_pages:
            url, depth = queue.popleft()
            try:
                response = fetcher.fetch(url)
                content_hash = digest(response.content)
                with Session.begin() as session:
                    page = session.scalar(
                        select(Page).where(Page.source_id == source_id, Page.url == url)
                    )
                    if page is None:
                        page = Page(
                            source_id=source_id,
                            url=url,
                            content_hash="",
                            checked_at=now(),
                        )
                        session.add(page)
                        session.flush()
                    if page.content_hash != content_hash:
                        metadata = {
                            "url": url,
                            "final_url": str(response.url),
                            "fetched_at": now().isoformat(),
                            "content_hash": content_hash,
                            "content_type": response.headers["content-type"],
                            "last_modified": response.headers.get("last-modified"),
                        }
                        path = save(
                            settings.raw_dir, source_id, response.content, metadata
                        )
                        session.add(
                            Snapshot(
                                page_id=page.id,
                                job_id=job_id,
                                content_hash=content_hash,
                                path=path,
                                last_modified=metadata["last_modified"],
                                content_type=metadata["content_type"],
                            )
                        )
                        page.content_hash = content_hash
                        created += 1
                    page.checked_at = now()
                if depth < max_depth:
                    links = Links(str(response.url))
                    links.feed(response.text)
                    for target in links.urls:
                        if target not in seen:
                            if len(seen) >= max_pages:
                                truncated = True
                                continue
                            seen.add(target)
                            queue.append((target, depth + 1))
            except Exception as exc:
                errors.append({"url": url, "error": str(exc)[:500]})
            checked += 1
            with Session.begin() as session:
                job = session.get(Job, job_id)
                job.pages_checked = checked
                job.snapshots_created = created
                job.errors = errors
                job.truncated = truncated
        if errors:
            raise RuntimeError(f"{len(errors)} page(s) failed; inspect job.errors")
    finally:
        fetcher.close()
