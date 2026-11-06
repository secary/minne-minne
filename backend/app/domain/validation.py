"""Deterministic candidate validation; source truth and publishing live elsewhere."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from backend.app.domain.markdown import WikiDocument, expected_path, prose
from backend.app.domain.wiki import (
    PAGE_ID_PATTERN,
    PAGE_SECTIONS,
    EvidenceRecord,
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    page_id: str | None = None
    severity: Literal["error", "warning"] = "error"


def validate_documents(
    documents: Iterable[WikiDocument],
    *,
    evidence_catalog: Mapping[UUID, EvidenceRecord] | None = None,
    for_publication: bool = False,
) -> list[ValidationIssue]:
    """Validate a complete candidate set; drafts may contain unresolved targets."""
    documents = list(documents)
    issues = []
    if not documents:
        return [ValidationIssue("empty_wiki", "no Wiki documents found")]
    known_ids = {document.metadata.id for document in documents}
    seen_ids, seen_paths = set(), set()
    pending_severity = "error" if for_publication else "warning"
    for document in documents:
        page = document.metadata

        def add(code, message, severity="error"):
            issues.append(ValidationIssue(code, message, page.id, severity))

        if page.id in seen_ids:
            add("duplicate_page_id", f"duplicate page id: {page.id}")
        seen_ids.add(page.id)
        if document.path is not None:
            if document.path in seen_paths:
                add("duplicate_path", f"duplicate page path: {document.path}")
            seen_paths.add(document.path)
            if document.path != expected_path(page):
                add("invalid_path", f"expected page path: {expected_path(page)}")

        body = prose(document.body)
        headings = [
            (len(mark), re.sub(r"[ \t]+#+[ \t]*$", "", title).strip())
            for mark, title in re.findall(r"^ {0,3}(#{1,6})[ \t]+(.+)$", body, re.M)
        ]
        if [title for level, title in headings if level == 1] != [page.title]:
            add("invalid_title", "body must contain one # heading matching title")
        sections = [title for level, title in headings if level == 2]
        missing = [
            section for section in PAGE_SECTIONS[page.type] if section not in sections
        ]
        if missing:
            add(
                "missing_section", f"missing required ## sections: {', '.join(missing)}"
            )
        if len(sections) != len(set(sections)):
            add("duplicate_section", "duplicate ## section heading")

        citations = set(re.findall(r"(?<!\\)\[@([^\]\n]*)\]", body))
        known_citations = {source.id for source in page.sources}
        if not citations:
            add(
                "missing_citation",
                "body must cite source evidence using [@citation-id]",
            )
        for citation in sorted(citations - known_citations):
            add("undefined_citation", f"undefined citation: {citation}")
        used = citations | {
            c for conflict in page.conflicts for c in conflict.citations
        }
        for citation in sorted(known_citations - used):
            add("unused_citation", f"unused source citation: {citation}")

        targets = {relation.target for relation in page.relations}
        if page.applicability.event_id:
            targets.add(page.applicability.event_id)
        for link in re.findall(r"(?<!\\)\[\[([^\]\n]*)\]\]", body):
            target, separator, label = link.partition("|")
            if (
                not re.fullmatch(PAGE_ID_PATTERN, target)
                or len(target) > 128
                or (separator and not label.strip())
            ):
                add("invalid_link", f"invalid Wiki link: [[{link}]]")
            else:
                targets.add(target)
        for target in sorted(targets - known_ids):
            add("missing_page", f"missing page target: {target}", pending_severity)

        for conflict in page.conflicts:
            if conflict.status == "unresolved":
                add(
                    "unresolved_conflict",
                    f"unresolved conflict: {conflict.summary}",
                    pending_severity,
                )
        if evidence_catalog is None:
            add(
                "evidence_unchecked",
                "no evidence catalog; snapshot and locator not verified",
                pending_severity,
            )
        else:
            for source in page.sources:
                record = evidence_catalog.get(source.snapshot_id)
                if record is None:
                    add(
                        "missing_snapshot",
                        f"unknown snapshot for citation: {source.id}",
                    )
                elif record.source_id != source.source_id:
                    add("source_mismatch", f"snapshot source_id mismatch: {source.id}")
                elif source.locator not in record.locators:
                    add(
                        "missing_locator",
                        f"unknown evidence locator: {source.id}: {source.locator}",
                    )

    issues.extend(_form_cycles(documents))
    return issues


def _form_cycles(documents: list[WikiDocument]) -> list[ValidationIssue]:
    parents = {
        document.metadata.id: relation.target
        for document in documents
        for relation in document.metadata.relations
        if relation.kind == "form_of"
    }
    done = set()
    issues = []
    for page_id in parents:
        chain = {}
        current = page_id
        while current in parents and current not in done:
            if current in chain:
                cycle = list(chain)[chain[current] :] + [current]
                issues.append(
                    ValidationIssue(
                        "form_cycle", f"form_of cycle: {' -> '.join(cycle)}", current
                    )
                )
                break
            chain[current] = len(chain)
            current = parents[current]
        done.update(chain)
    return issues
