import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.models import Base, Job, Source
from backend.app.worker.main import main, run_once


class SingleRoundTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.cutoff = datetime(2100, 1, 15, tzinfo=UTC)
        self.lock = MagicMock()
        for name, value in (
            ("Session", self.sessions),
            ("now", MagicMock(return_value=self.cutoff)),
        ):
            patcher = patch(f"backend.app.worker.main.{name}", value)
            patched = patcher.start()
            self.addCleanup(patcher.stop)
            if name == "now":
                self.clock = patched

    def add_source(self, source_id, *, due=False):
        with self.sessions.begin() as session:
            session.add(
                Source(
                    id=source_id,
                    name=source_id,
                    url=f"https://wikiwiki.jp/kancolle/{source_id}",
                    next_run_at=self.cutoff + timedelta(days=-1 if due else 30),
                )
            )

    def add_job(self, source_id, **values):
        with self.sessions.begin() as session:
            job = Job(
                source_id=source_id,
                **(
                    {
                        "created_at": self.cutoff - timedelta(minutes=1),
                        "available_at": self.cutoff - timedelta(minutes=1),
                    }
                    | values
                ),
            )
            session.add(job)
            session.flush()
            return job.id

    def test_round_schedules_and_finishes_all_ready_sources(self):
        self.add_source("first", due=True)
        self.add_source("second", due=True)

        with patch("backend.app.worker.main.crawl"):
            run_once(self.lock)
            run_once(self.lock)

        with self.sessions() as session:
            jobs = session.scalars(select(Job)).all()
            self.assertEqual(len(jobs), 2)
            self.assertEqual({job.source_id for job in jobs}, {"first", "second"})
            for job in jobs:
                self.assertEqual(job.status, "succeeded")
                self.assertEqual(job.attempts, 1)
                self.assertIsNotNone(job.finished_at)

    def test_empty_round_exits_without_sleeping(self):
        self.add_source("later")
        with patch(
            "backend.app.worker.main.time.sleep",
            side_effect=AssertionError("A single round must not wait"),
        ):
            run_once(self.lock)
        with self.sessions() as session:
            self.assertIsNone(session.scalar(select(Job)))

    def test_future_task_is_deferred_even_when_another_crawl_runs_past_its_time(self):
        self.add_source("ready")
        self.add_source("later")
        ready_id = self.add_job("ready")
        later_id = self.add_job(
            "later", available_at=self.cutoff + timedelta(minutes=5)
        )

        def crawl(_job_id):
            self.clock.return_value = self.cutoff + timedelta(minutes=10)

        with patch("backend.app.worker.main.crawl", side_effect=crawl):
            run_once(self.lock)

        with self.sessions() as session:
            self.assertEqual(session.get(Job, ready_id).status, "succeeded")
            later = session.get(Job, later_id)
            self.assertEqual(later.status, "pending")
            self.assertEqual(later.attempts, 0)

    def test_failed_task_waits_for_next_round_while_other_ready_work_finishes(self):
        self.add_source("retry")
        self.add_source("success")
        retry_id = self.add_job("retry")
        success_id = self.add_job("success", created_at=self.cutoff)

        def crawl(job_id):
            if job_id == retry_id:
                raise RuntimeError("offline")
            self.clock.return_value = self.cutoff + timedelta(minutes=20)

        with patch("backend.app.worker.main.crawl", side_effect=crawl):
            run_once(self.lock)

        with self.sessions() as session:
            retry = session.get(Job, retry_id)
            self.assertEqual(retry.status, "pending")
            self.assertEqual(retry.attempts, 1)
            self.assertEqual(retry.error, "offline")
            self.assertGreater(
                retry.available_at.replace(tzinfo=self.cutoff.tzinfo), self.cutoff
            )
            self.assertEqual(session.get(Job, success_id).status, "succeeded")

    def test_jobs_created_during_round_wait_until_next_start(self):
        self.add_source("first")
        self.add_source("new")
        first_id = self.add_job("first")
        new_ids = []

        def crawl(job_id):
            if job_id == first_id:
                new_ids.append(
                    self.add_job("new", created_at=self.cutoff + timedelta(seconds=1))
                )

        with patch("backend.app.worker.main.crawl", side_effect=crawl):
            run_once(self.lock)

        with self.sessions() as session:
            self.assertEqual(session.get(Job, first_id).status, "succeeded")
            added = session.get(Job, new_ids[0])
            self.assertEqual(added.status, "pending")
            self.assertEqual(added.attempts, 0)

    def test_lost_lock_stops_round_before_claiming(self):
        self.add_source("due", due=True)
        self.add_source("ready")
        job_id = self.add_job("ready")
        self.lock.execute.side_effect = RuntimeError("lock connection lost")

        with self.assertRaisesRegex(RuntimeError, "lock connection lost"):
            run_once(self.lock)

        with self.sessions() as session:
            job = session.get(Job, job_id)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.attempts, 0)
            jobs = session.scalars(select(Job)).all()
            self.assertEqual(len(jobs), 1)
            source = session.get(Source, "due")
            self.assertEqual(
                source.next_run_at.replace(tzinfo=UTC),
                self.cutoff - timedelta(days=1),
            )

    def test_once_start_recovers_interrupted_jobs_and_honors_retry_limit(self):
        self.add_source("interrupted")
        self.add_source("exhausted")
        interrupted_id = self.add_job("interrupted", status="running", attempts=1)
        exhausted_id = self.add_job("exhausted", status="running", attempts=3)
        fake_engine = MagicMock()
        fake_engine.connect.return_value.__enter__.return_value = self.lock
        self.lock.scalar.return_value = True

        with (
            patch("backend.app.worker.main.engine", fake_engine),
            patch("backend.app.worker.main.sync_sources"),
            patch("backend.app.worker.main.crawl"),
            patch(
                "backend.app.worker.main.time.sleep",
                side_effect=AssertionError("A single round must not wait"),
            ),
        ):
            main(["--once"])

        with self.sessions() as session:
            interrupted = session.get(Job, interrupted_id)
            self.assertEqual(interrupted.status, "succeeded")
            self.assertEqual(interrupted.attempts, 2)
            self.assertIsNone(interrupted.error)
            exhausted = session.get(Job, exhausted_id)
            self.assertEqual(exhausted.status, "failed")
            self.assertEqual(exhausted.attempts, 3)
            self.assertEqual(exhausted.error, "Worker interrupted")
            self.assertIsNotNone(exhausted.finished_at)
