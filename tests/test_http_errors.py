import unittest
from unittest.mock import patch

import httpx

from backend.app.ingestion.http import Fetcher

SEED = "https://wikiwiki.jp/kancolle/"


class ConnectionErrorTests(unittest.TestCase):
    def setUp(self):
        self.failure = None

        def refuse(request):
            self.failure = httpx.ConnectError(
                "[Errno 111] Connection refused", request=request
            )
            raise self.failure

        client = httpx.Client(transport=httpx.MockTransport(refuse), trust_env=False)
        self.fetcher = Fetcher("MinneMinne", 0, client=client)
        self.addCleanup(self.fetcher.close)
        sleeper = patch("backend.app.ingestion.http.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_connection_failure_has_request_context_and_preserves_type_and_cause(self):
        with self.assertRaises(httpx.ConnectError) as caught:
            self.fetcher.request(SEED)

        error = caught.exception
        self.assertIn(SEED, str(error))
        self.assertIn("HTTP_PROXY/HTTPS_PROXY/ALL_PROXY", str(error))
        self.assertIn("localhost/127.0.0.1 refers to the container", str(error))
        self.assertIn("host.docker.internal", str(error))
        self.assertIs(error.__cause__, self.failure)
        self.assertIs(error.request, self.failure.request)

    def test_diagnostic_url_does_not_expose_credentials(self):
        with self.assertRaises(httpx.ConnectError) as caught:
            self.fetcher.request("https://crawl-user:secret-pass@wikiwiki.jp/kancolle/")

        message = str(caught.exception)
        self.assertIn(SEED, message)
        self.assertNotIn("crawl-user", message)
        self.assertNotIn("secret-pass", message)

    def test_robots_connection_failure_identifies_robots_url(self):
        with self.assertRaises(httpx.ConnectError) as caught:
            self.fetcher.load_robots(SEED)

        self.assertIn("https://wikiwiki.jp/robots.txt", str(caught.exception))
        self.assertIsNone(self.fetcher.robots)
