import gzip
import unittest
import zlib
from unittest.mock import patch

import httpx

from backend.app.ingestion.http import Fetcher

SEED = "https://wikiwiki.jp/kancolle/"
COMPRESSORS = {"gzip": gzip.compress, "deflate": zlib.compress}


class ChunkedStream(httpx.SyncByteStream):
    def __init__(self, content: bytes):
        self.content = content

    def __iter__(self):
        for offset in range(0, len(self.content), 7):
            yield self.content[offset : offset + 7]


class CompressionTests(unittest.TestCase):
    def setUp(self):
        sleeper = patch("backend.app.ingestion.http.time.sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def fetcher(self, content, encoding, *, status=200, headers=None):
        compressed = COMPRESSORS[encoding](content)
        response_headers = {
            "content-encoding": encoding,
            "content-length": str(len(compressed)),
        } | (headers or {})
        if "transfer-encoding" in response_headers:
            response_headers.pop("content-length")

        def respond(request):
            return httpx.Response(
                status,
                headers=response_headers,
                stream=ChunkedStream(compressed),
                request=request,
            )

        client = httpx.Client(transport=httpx.MockTransport(respond), trust_env=False)
        fetcher = Fetcher("MinneMinne", 0, client=client)
        self.addCleanup(fetcher.close)
        return fetcher

    def test_decoded_body_has_matching_headers_and_preserves_metadata(self):
        content = "<html>艦娘の資料</html>".encode() * 100
        last_modified = "Tue, 03 Nov 2026 00:00:00 GMT"
        for encoding in COMPRESSORS:
            for chunked in (False, True):
                with self.subTest(encoding=encoding, chunked=chunked):
                    headers = {
                        "content-type": "text/html; charset=utf-8",
                        "last-modified": last_modified,
                    }
                    if chunked:
                        headers["transfer-encoding"] = "chunked"
                    fetcher = self.fetcher(
                        content, encoding, status=203, headers=headers
                    )
                    response = fetcher.request(SEED)

                    self.assertEqual(response.content, content)
                    self.assertEqual(response.text, content.decode())
                    self.assertEqual(response.status_code, 203)
                    self.assertEqual(response.url, httpx.URL(SEED))
                    self.assertEqual(response.request.method, "GET")
                    self.assertEqual(
                        response.headers["content-type"],
                        "text/html; charset=utf-8",
                    )
                    self.assertEqual(response.headers["last-modified"], last_modified)
                    self.assertNotIn("content-encoding", response.headers)
                    self.assertNotIn("transfer-encoding", response.headers)
                    self.assertEqual(
                        int(response.headers["content-length"]), len(content)
                    )

    def test_compressed_robots_rules_are_parsed(self):
        content = b"User-agent: *\nDisallow: /kancolle/private\nCrawl-delay: 5\n"
        for encoding in COMPRESSORS:
            with self.subTest(encoding=encoding):
                fetcher = self.fetcher(
                    content, encoding, headers={"content-type": "text/plain"}
                )
                fetcher.load_robots(SEED)

                self.assertEqual(fetcher.delay, 5)
                self.assertTrue(fetcher.robots.can_fetch(fetcher.agent, SEED))
                with self.assertRaisesRegex(ValueError, "disallowed by robots"):
                    fetcher.fetch(SEED + "private")

    def test_size_limit_applies_to_decompressed_content(self):
        content = b"A" * 1024
        limit = 128
        for encoding, compress in COMPRESSORS.items():
            with self.subTest(encoding=encoding):
                self.assertLess(len(compress(content)), limit)
                fetcher = self.fetcher(content, encoding)
                with patch("backend.app.ingestion.http.MAX_BYTES", limit):
                    with self.assertRaisesRegex(ValueError, "exceeds 10 MiB"):
                        fetcher.request(SEED)
