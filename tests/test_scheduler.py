import unittest
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.models import Base, Job, Source, now
from backend.app.worker.main import enqueue, tick


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        with self.sessions.begin() as session:
            session.add(
                Source(id="source", name="wiki", url="https://wikiwiki.jp/kancolle/")
            )
        patcher = patch("backend.app.worker.main.Session", self.sessions)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_enqueue_idempotent(self):
        with self.sessions.begin() as session:
            source = session.get(Source, "source")
            self.assertEqual(enqueue(session, source).id, enqueue(session, source).id)

    def test_schedule_success_and_no_duplicate(self):
        with patch("backend.app.worker.main.crawl"):
            tick()
            tick()
        with self.sessions() as session:
            jobs = session.scalars(select(Job)).all()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0].status, "succeeded")
            self.assertEqual(jobs[0].attempts, 1)
            self.assertIsNotNone(jobs[0].finished_at)

    def test_retry_limit(self):
        with patch(
            "backend.app.worker.main.crawl", side_effect=RuntimeError("offline")
        ):
            for attempt in range(1, 4):
                tick()
                with self.sessions.begin() as session:
                    job = session.scalar(select(Job))
                    self.assertEqual(job.attempts, attempt)
                    self.assertEqual(
                        job.status, "failed" if attempt == 3 else "pending"
                    )
                    self.assertEqual(job.error, "offline")
                    job.available_at = now() - timedelta(seconds=1)

    def test_disabled_source_not_scheduled(self):
        with self.sessions.begin() as session:
            session.get(Source, "source").enabled = False
        tick()
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(Job)))
