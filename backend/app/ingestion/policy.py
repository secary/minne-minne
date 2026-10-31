import calendar
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

ROOTS = {
    "wikiwiki.jp": "/kancolle/",
    "zh.kcwiki.cn": "/wiki/",
}


def normalize(url: str, base: str) -> str | None:
    parts = urlsplit(urljoin(base, url))
    root = ROOTS.get(parts.hostname or "")
    path = unquote(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc != urlsplit(base).netloc
        or parts.username
        or parts.port not in (None, 443)
        or not root
        or not path.startswith(root)
        or parts.query
        or any(piece in (".", "..") for piece in path.split("/"))
    ):
        return None
    title = path[len(root) :]
    if ":" in title or title.startswith(("コメント", "管理", "Recent", "Menu", "Side")):
        return None
    return urlunsplit(("https", parts.netloc, quote(path, safe="/()_-~"), "", ""))


def next_month(current: datetime, months: int) -> datetime:
    offset = current.year * 12 + current.month - 1 + months
    year, month = divmod(offset, 12)
    month += 1
    day = min(current.day, calendar.monthrange(year, month)[1])
    return current.replace(year=year, month=month, day=day)


class Links(HTMLParser):
    def __init__(self, base: str):
        super().__init__()
        self.base = base
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and (url := normalize(href, self.base)) and url not in self.urls:
                self.urls.append(url)
