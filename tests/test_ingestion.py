import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.models import Base, Job, Page, Snapshot, Source
from backend.app.ingestion.http import Fetcher
from backend.app.ingestion.policy import Links, next_month, normalize
from backend.app.ingestion.storage import digest, save
from backend.app.worker.crawl import crawl

SEED = "https://wikiwiki.jp/kancolle/"


class PolicyTests(unittest.TestCase):
    def test_calendar_month(self):
        date = datetime(2024, 1, 31, 12, tzinfo=UTC)
        self.assertEqual(next_month(date, 1), date.replace(month=2, day=29))
        self.assertEqual(next_month(date, 12), date.replace(year=2025))

    def test_scope(self):
        self.assertEqual(normalize("赤城#data", SEED), SEED + "%E8%B5%A4%E5%9F%8E")
        for url in [
            "https://example.com/",
            "http://wikiwiki.jp/kancolle/",
            "/other/",
            "?cmd=edit",
            "../",
            "%2e%2e/secret",
            "コメント/赤城",
            "File:example",
            "javascript:alert(1)",
        ]:
            with self.subTest(url=url):
                self.assertIsNone(normalize(url, SEED))

    def test_link_deduplication(self):
        links = Links(SEED)
        links.feed('<a href="赤城">a</a><a href="赤城#x">b</a><a href="/other/">x</a>')
        self.assertEqual(len(links.urls), 1)

    def test_snapshot_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = save(root, "source", b"old", {"url": SEED})
            second = save(root, "source", b"new", {"url": SEED})
            self.assertNotEqual(first, second)
            self.assertEqual((root / first).read_bytes(), b"old")
            self.assertEqual(
                json.loads((root / first).with_name("metadata.json").read_text()),
                {"url": SEED},
            )
            self.assertNotEqual(digest(b"old"), digest(b"new"))


class FetchTests(unittest.TestCase):
    def setUp(self):
        client = httpx.Client(
            transport=httpx.MockTransport(lambda request: self.response()),
            trust_env=False,
        )
        self.fetcher = Fetcher("MinneMinne", 1, client=client)
        self.addCleanup(self.fetcher.close)

    def response(self, code=200, body=b"", **headers):
        return httpx.Response(
            code, content=body, headers=headers, request=httpx.Request("GET", SEED)
        )

    def test_robots_and_redirect(self):
        responses = [
            self.response(
                body=b"User-agent: *\nDisallow: /kancolle/private\nCrawl-delay: 5"
            ),
            self.response(302, location="/kancolle/next"),
            self.response(body=b"ok", **{"content-type": "text/html"}),
        ]
        with patch.object(self.fetcher, "request", side_effect=responses):
            self.fetcher.load_robots(SEED)
            self.assertEqual(self.fetcher.delay, 5)
            with self.assertRaisesRegex(ValueError, "robots"):
                self.fetcher.fetch(SEED + "private")
            self.assertEqual(self.fetcher.fetch(SEED).content, b"ok")

    def test_failure_paths(self):
        with patch.object(self.fetcher, "request", return_value=self.response(503)):
            with self.assertRaises(httpx.HTTPStatusError):
                self.fetcher.load_robots(SEED)
        with patch.object(self.fetcher, "request", return_value=self.response(404)):
            self.fetcher.load_robots(SEED)
        for response in [
            self.response(302, location="https://example.com"),
            self.response(),
        ]:
            with patch.object(self.fetcher, "request", return_value=response):
                with self.assertRaises(ValueError):
                    self.fetcher.fetch(SEED)

    def test_stream_limit(self):
        transport = httpx.MockTransport(lambda request: self.response(body=b"12345"))
        self.fetcher.client.close()
        self.fetcher.client = httpx.Client(transport=transport, trust_env=False)
        with patch("backend.app.ingestion.http.MAX_BYTES", 4):
            with self.assertRaisesRegex(ValueError, "10 MiB"):
                self.fetcher.request(SEED)

    def test_injected_client_ignores_proxy_environment(self):
        def respond(request):
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            return httpx.Response(
                200, content=b"archived content", headers={"content-type": "text/html"}
            )

        with patch.dict(
            "os.environ",
            {
                "ALL_PROXY": "socks5://127.0.0.1:1",
                "HTTPS_PROXY": "socks5://127.0.0.1:1",
                "SSL_CERT_FILE": "/nonexistent/minne-test-certificate.pem",
            },
        ):
            client = httpx.Client(
                transport=httpx.MockTransport(respond), trust_env=False
            )
            fetcher = Fetcher("MinneMinne", 1, client=client)
            self.addCleanup(fetcher.close)
            with patch("backend.app.ingestion.http.time.sleep"):
                fetcher.load_robots(SEED)
                self.assertEqual(fetcher.fetch(SEED).content, b"archived content")


class CrawlTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.engine.dispose)
        with self.sessions.begin() as session:
            session.add(Source(id="source", name="wiki", url=SEED, max_pages=1))
            session.flush()
            session.add(Job(id="job", source_id="source"))
        self.patches = [
            patch("backend.app.worker.crawl.Session", self.sessions),
            patch(
                "backend.app.worker.crawl.settings.raw_dir", Path(self.directory.name)
            ),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        fetcher_patch = patch("backend.app.worker.crawl.Fetcher", autospec=True)
        self.fetcher = fetcher_patch.start().return_value
        self.addCleanup(fetcher_patch.stop)
        self.fetcher.fetch.side_effect = self.fetch
        self.body = b'<html><a href="next">next</a></html>'

    def fetch(self, url):
        return httpx.Response(
            200,
            content=self.body,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", url),
        )

    def test_change_detection_and_cap(self):
        crawl("job")
        crawl("job")
        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(Snapshot)).all()), 1)
            self.assertTrue(session.get(Job, "job").truncated)
            self.assertEqual(session.get(Job, "job").pages_checked, 1)
        self.body = b"changed"
        crawl("job")
        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(Snapshot)).all()), 2)
            self.assertEqual(len(session.scalars(select(Page)).all()), 1)

    def test_failed_page_recorded(self):
        self.fetcher.fetch.side_effect = ValueError("offline")
        with self.assertRaisesRegex(RuntimeError, "1 page"):
            crawl("job")
        with self.sessions() as session:
            self.assertEqual(session.get(Job, "job").errors[0]["error"], "offline")
            self.assertEqual(len(session.scalars(select(Snapshot)).all()), 0)
