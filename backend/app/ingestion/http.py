import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from backend.app.ingestion.policy import normalize

MAX_BYTES = 10 * 1024 * 1024


class Fetcher:
    def __init__(
        self, user_agent: str, delay: int, *, client: httpx.Client | None = None
    ):
        self.agent = user_agent
        self.delay = delay
        self.last_request = 0.0
        self.client = (
            client
            if client is not None
            else httpx.Client(
                headers={"User-Agent": user_agent}, timeout=30, follow_redirects=False
            )
        )
        self.robots: RobotFileParser | None = None

    def close(self):
        self.client.close()

    def request(self, url: str):
        time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        with self.client.stream("GET", url) as response:
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError("Response exceeds 10 MiB")
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=response.request,
            )

    def load_robots(self, url: str):
        origin = urlsplit(url)
        response = self.request(f"{origin.scheme}://{origin.netloc}/robots.txt")
        parser = RobotFileParser()
        if response.status_code == 404:
            parser.parse([])
        else:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("robots.txt redirects require manual review")
            parser.parse(response.text.splitlines())
        self.robots = parser
        self.delay = max(self.delay, parser.crawl_delay(self.agent) or 0)

    def fetch(self, url: str):
        for _ in range(6):
            if not self.robots or not self.robots.can_fetch(self.agent, url):
                raise ValueError("URL disallowed by robots.txt")
            response = self.request(url)
            if response.is_redirect:
                target = normalize(response.headers.get("location", ""), url)
                if not target:
                    raise ValueError("Redirect leaves allowed wiki scope")
                url = target
                continue
            response.raise_for_status()
            if "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Expected HTML document")
            return response
        raise ValueError("Too many redirects")
