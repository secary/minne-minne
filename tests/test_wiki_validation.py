from dataclasses import replace
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from backend.app.domain.markdown import WikiDocument, expected_path
from backend.app.domain.validation import validate_documents
from backend.app.domain.wiki import PAGE_SECTIONS, EvidenceRecord, PageType, WikiPage

SNAPSHOT = UUID("c072f8c8-b1c0-48e7-9006-762439d12470")
LOCATOR = "section:改造/table:1/row:2"


def document(page_id="ship:akagi", *, body=None, **updates):
    values = {
        "schema_version": "1",
        "id": page_id,
        "type": page_id.split(":")[0],
        "title": "测试页面",
        "sources": [
            {
                "id": "c1",
                "source_id": "wikiwiki-kancolle",
                "snapshot_id": SNAPSHOT,
                "locator": LOCATOR,
            }
        ],
        "applicability": {"scope": "permanent"},
    }
    values.update(updates)
    page = WikiPage.model_validate(values)
    if body is None:
        sections = "\n\n".join(
            f"## {section}\n\n资料。" for section in PAGE_SECTIONS[page.type]
        )
        body = f"# {page.title}\n\n结论。[@c1]\n\n{sections}"
    return WikiDocument(metadata=page, body=body, path=expected_path(page))


def catalog(**updates):
    values = {"source_id": "wikiwiki-kancolle", "locators": [LOCATOR, "paragraph:2"]}
    values.update(updates)
    return {SNAPSHOT: EvidenceRecord.model_validate(values)}


def issues_for(*documents, for_publication=False, evidence_catalog=None):
    return validate_documents(
        documents,
        for_publication=for_publication,
        evidence_catalog=evidence_catalog,
    )


def errors(issues):
    return [issue for issue in issues if issue.severity == "error"]


def test_empty_candidate_cannot_be_published():
    assert errors(issues_for(for_publication=True, evidence_catalog=catalog()))


@pytest.mark.parametrize("page_type", list(PageType))
def test_complete_page_with_verified_evidence_is_structurally_publishable(page_type):
    issues = issues_for(
        document(f"{page_type}:example"),
        for_publication=True,
        evidence_catalog=catalog(),
    )
    assert issues == []


@pytest.mark.parametrize(
    "modify",
    [
        lambda body: body.replace("# 测试页面", "# 错误标题", 1),
        lambda body: body + "\n\n# 第二个主标题",
        lambda body: body.replace("## 概述", "### 概述", 1),
        lambda body: body + "\n\n## 概述\n\n重复小节。",
        lambda body: body.replace("[@c1]", "[@missing]"),
        lambda body: body.replace("[@c1]", ""),
    ],
)
def test_invalid_headings_and_citations_block_validation(modify):
    valid = document()
    issues = issues_for(
        replace(valid, body=modify(valid.body)), evidence_catalog=catalog()
    )
    assert errors(issues)


def test_all_declared_citations_must_support_visible_content_or_conflicts():
    valid = document()
    sources = [source.model_dump() for source in valid.metadata.sources]
    sources.append({**sources[0], "id": "c2", "locator": "paragraph:2"})
    issues = issues_for(document(sources=sources), evidence_catalog=catalog())
    assert errors(issues)


@pytest.mark.parametrize(
    "sample",
    [
        "`[@c1]`",
        "```markdown\n[@c1]\n```",
        "~~~markdown\n[@c1]\n~~~",
        "<!-- [@c1] -->",
    ],
)
def test_examples_and_comments_cannot_supply_a_real_citation(sample):
    valid = document()
    issues = issues_for(
        replace(valid, body=valid.body.replace("[@c1]", sample)),
        evidence_catalog=catalog(),
    )
    assert errors(issues)


def test_headings_and_links_inside_examples_do_not_change_page_semantics():
    valid = document()
    sample = (
        "\n\n```markdown\n# 错误标题\n[[ship:missing]]\n[@missing]\n```"
        "\n\n`[[ship:other]]` <!-- [[ship:missing]] [@missing] -->"
    )
    assert not issues_for(
        replace(valid, body=valid.body + sample),
        for_publication=True,
        evidence_catalog=catalog(),
    )


@pytest.mark.parametrize("example", ["```html\n<!--\n```", "`<!--`", "`` <!-- ``"])
def test_literal_html_comment_openers_in_code_cannot_hide_real_evidence(example):
    valid = document()
    assert not issues_for(
        replace(valid, body=example + "\n\n" + valid.body),
        for_publication=True,
        evidence_catalog=catalog(),
    )


@pytest.mark.parametrize("citation", ["``[@c1]`", "```[@c1]``", "``[@c1]```"])
def test_unequal_backtick_runs_cannot_consume_a_visible_citation(citation):
    valid = document()
    assert not issues_for(
        replace(valid, body=valid.body.replace("[@c1]", citation)),
        for_publication=True,
        evidence_catalog=catalog(),
    )


def test_known_wiki_links_and_relations_resolve_by_stable_id():
    valid = document()
    linked = replace(valid, body=valid.body + "\n\n参见 [[ship:kaga|加贺]]。")
    assert not issues_for(
        linked,
        document("ship:kaga", relations=[{"target": "ship:akagi"}]),
        for_publication=True,
        evidence_catalog=catalog(),
    )


@pytest.mark.parametrize("link", ["[[../ship:akagi]]", "[[ship:akagi| ]]", "[[赤城]]"])
def test_malformed_wiki_targets_cannot_bypass_link_validation(link):
    valid = document()
    issues = issues_for(
        replace(valid, body=valid.body + "\n\n" + link), evidence_catalog=catalog()
    )
    assert any(issue.code == "invalid_link" for issue in errors(issues))


@pytest.mark.parametrize("target_kind", ["body", "relation", "event"])
def test_missing_page_targets_warn_in_drafts_and_block_publication(target_kind):
    valid = document()
    if target_kind == "body":
        valid = replace(valid, body=valid.body + "\n\n[[ship:missing]]")
    elif target_kind == "relation":
        valid = document(relations=[{"target": "ship:missing"}])
    else:
        valid = document(
            applicability={"scope": "historical_event", "event_id": "event:missing"}
        )
    draft = issues_for(valid, evidence_catalog=catalog())
    published = issues_for(valid, for_publication=True, evidence_catalog=catalog())
    assert draft and all(issue.severity == "warning" for issue in draft)
    assert errors(published)


def test_duplicate_page_ids_and_paths_are_rejected():
    valid = document()
    assert errors(issues_for(valid, valid, evidence_catalog=catalog()))
    other = replace(document("ship:kaga"), path=valid.path)
    assert errors(issues_for(valid, other, evidence_catalog=catalog()))


@pytest.mark.parametrize(
    "path",
    ["ships/renamed.md", "equipment/akagi.md", "../ships/akagi.md", "/ships/akagi.md"],
)
def test_paths_must_match_the_page_type_and_stable_slug(path):
    valid = replace(document(), path=PurePosixPath(path))
    assert errors(issues_for(valid, evidence_catalog=catalog()))


def test_remodel_relationship_cycles_are_rejected():
    akagi = document(relations=[{"target": "ship:akagi_kai", "kind": "form_of"}])
    remodel = document(
        "ship:akagi_kai", relations=[{"target": "ship:akagi", "kind": "form_of"}]
    )
    assert errors(issues_for(akagi, remodel, evidence_catalog=catalog()))


def test_missing_evidence_catalog_is_visible_and_blocks_publication():
    draft = issues_for(document())
    assert draft and all(issue.severity == "warning" for issue in draft)
    assert errors(issues_for(document(), for_publication=True))


@pytest.mark.parametrize(
    "evidence_catalog",
    [
        {},
        catalog(source_id="kcwiki-zh"),
        catalog(locators=["different:paragraph"]),
    ],
)
def test_catalog_must_confirm_snapshot_source_and_exact_location(evidence_catalog):
    issues = issues_for(document(), evidence_catalog=evidence_catalog)
    assert errors(issues)


def conflicted_page(*, resolved):
    valid = document()
    sources = [source.model_dump() for source in valid.metadata.sources]
    sources.append({**sources[0], "id": "c2", "locator": "paragraph:2"})
    conflict = {
        "summary": "两份资料给出的适用条件不同",
        "citations": ["c1", "c2"],
        "status": "resolved" if resolved else "unresolved",
    }
    if resolved:
        conflict["resolution"] = "分别适用于不同活动阶段，保留两方证据。"
    return document(sources=sources, conflicts=[conflict])


def test_unresolved_conflicts_remain_visible_and_block_publication():
    valid = conflicted_page(resolved=False)
    draft = issues_for(valid, evidence_catalog=catalog())
    assert draft and all(issue.severity == "warning" for issue in draft)
    assert errors(issues_for(valid, for_publication=True, evidence_catalog=catalog()))


def test_conflict_evidence_remains_referenced_after_resolution():
    assert not issues_for(
        conflicted_page(resolved=True),
        for_publication=True,
        evidence_catalog=catalog(),
    )
