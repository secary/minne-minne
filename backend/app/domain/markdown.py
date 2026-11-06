"""Safe YAML frontmatter I/O and the small Markdown subset used by the schema."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

import frontmatter
import yaml
from frontmatter.default_handlers import YAMLHandler

from backend.app.domain.wiki import PAGE_DIRECTORIES, WikiPage


class _UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("frontmatter keys must be strings")
            if key in mapping:
                raise ValueError(f"duplicate YAML key: {key}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


class _YAMLHandler(YAMLHandler):
    # Exact delimiter lines avoid treating Markdown horizontal rules as metadata.
    FM_BOUNDARY = re.compile(r"^---[ \t]*$", re.MULTILINE)

    def load(self, fm, **kwargs):
        data = yaml.load(fm, Loader=_UniqueKeyLoader)
        if not isinstance(data, dict):
            raise ValueError("frontmatter must be a YAML mapping")
        return data


@dataclass(frozen=True)
class WikiDocument:
    metadata: WikiPage
    body: str
    path: PurePosixPath | None = None


def parse_document(text: str, *, path: PurePosixPath | None = None) -> WikiDocument:
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if not text.splitlines() or text.splitlines()[0].strip() != "---":
        raise ValueError("document must start with YAML frontmatter")
    if len(_YAMLHandler.FM_BOUNDARY.findall(text)) < 2:
        raise ValueError("frontmatter closing delimiter is missing")
    try:
        post = frontmatter.loads(text, handler=_YAMLHandler())
    except (yaml.YAMLError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid YAML frontmatter: {exc}") from exc
    metadata = WikiPage.model_validate(post.metadata)
    return WikiDocument(metadata, post.content, path)


def dump_document(document: WikiDocument) -> str:
    metadata = document.metadata.model_dump(mode="json", exclude_none=True)
    post = frontmatter.Post(document.body.strip(), **metadata)
    return frontmatter.dumps(post, sort_keys=False, allow_unicode=True) + "\n"


def expected_path(page: WikiPage) -> PurePosixPath:
    slug = page.id.split(":", 1)[1]
    return PurePosixPath(PAGE_DIRECTORIES[page.type], f"{slug}.md")


def prose(body: str) -> str:
    """Ignore comments and code when inspecting headings, links and citations."""
    parts = []
    fence = None
    cursor = 0
    while cursor < len(body):
        if cursor == 0 or body[cursor - 1] == "\n":
            end = body.find("\n", cursor)
            end = len(body) if end == -1 else end
            next_line = end + 1 if end < len(body) else end
            line = body[cursor:end]
            match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
            opens = match and (match[1][0] == "~" or "`" not in match[2])
            if fence or opens:
                if fence:
                    if match and (
                        match[1][0] == fence[0]
                        and len(match[1]) >= len(fence)
                        and not match[2].strip()
                    ):
                        fence = None
                else:
                    fence = match[1]
                parts.append(_mask(body[cursor:next_line]))
                cursor = next_line
                continue
            if line.startswith(("    ", "\t")):
                parts.append(_mask(body[cursor:next_line]))
                cursor = next_line
                continue
        if body.startswith("<!--", cursor):
            end = body.find("-->", cursor + 4)
            end = len(body) if end == -1 else end + 3
            parts.append(_mask(body[cursor:end]))
            cursor = end
            continue
        if body[cursor] == "`":
            run = re.match(r"`+", body[cursor:])[0]
            end = _code_end(body, cursor + len(run), len(run))
            if end is not None:
                parts.append(_mask(body[cursor:end]))
                cursor = end
            else:
                parts.append(run)
                cursor += len(run)
            continue
        if (
            body[cursor] == "\\"
            and cursor + 1 < len(body)
            and body[cursor + 1] in "`[]\\"
        ):
            parts.append("  ")
            cursor += 2
            continue
        parts.append(body[cursor])
        cursor += 1
    return "".join(parts)


def _mask(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def _code_end(body: str, start: int, length: int) -> int | None:
    # Inline spans cannot cross a paragraph or a new heading/fenced block.
    boundary = re.search(
        r"\n[ \t]*\n|\n {0,3}(?:#{1,6}[ \t]|`{3,}|~{3,})", body[start:]
    )
    end = start + boundary.start() if boundary else len(body)
    for match in re.compile(r"`+").finditer(body, start, end):
        if len(match[0]) == length:
            return match.end()
    return None
