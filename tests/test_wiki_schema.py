from datetime import date, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.domain.markdown import (
    WikiDocument,
    dump_document,
    expected_path,
    parse_document,
)
from backend.app.domain.wiki import PAGE_DIRECTORIES, PageType, WikiPage

SNAPSHOT = "c072f8c8-b1c0-48e7-9006-762439d12470"


def metadata(**updates):
    values = {
        "schema_version": "1",
        "id": "ship:akagi",
        "type": "ship",
        "title": "赤城",
        "aliases": ["Akagi", "赤城さん"],
        "sources": [
            {
                "id": "c1",
                "source_id": "wikiwiki-kancolle",
                "snapshot_id": SNAPSHOT,
                "locator": "section:改造/table:1/row:2",
            }
        ],
        "applicability": {"scope": "permanent"},
    }
    values.update(updates)
    return values


@pytest.mark.parametrize("page_type", list(PageType))
def test_each_page_type_has_a_stable_canonical_path(page_type):
    page = WikiPage.model_validate(
        metadata(id=f"{page_type}:example_01", type=page_type)
    )
    assert expected_path(page) == PurePosixPath(
        PAGE_DIRECTORIES[page_type], "example_01.md"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"schema_version": "2"},
        {"schema_version": 1},
        {"id": "equipment:akagi"},
        {"id": "ship:../akagi"},
        {"id": "ship:Akagi"},
        {"id": "ship:赤城"},
        {"id": "ship:" + "a" * 128},
        {"id": "ship:akagi\nextra"},
        {"title": "   "},
        {"type": "unknown"},
        {"sources": []},
        {"unexpected": "ignored data must fail"},
        {"applicability": {"scope": "unknown", "unexpected": True}},
    ],
)
def test_invalid_identity_and_unknown_metadata_fail(updates):
    with pytest.raises(ValidationError):
        WikiPage.model_validate(metadata(**updates))


@pytest.mark.parametrize("field", ["schema_version", "applicability", "sources"])
def test_compiler_must_explicitly_supply_required_metadata(field):
    values = metadata()
    del values[field]
    with pytest.raises(ValidationError):
        WikiPage.model_validate(values)


@pytest.mark.parametrize(
    "aliases", [["Akagi", " Akagi "], ["Akagi", "akagi"], ["赤城"], [" "]]
)
def test_ambiguous_or_empty_aliases_fail(aliases):
    with pytest.raises(ValidationError):
        WikiPage.model_validate(metadata(aliases=aliases))


def test_text_is_trimmed_and_citation_ids_are_unique():
    values = metadata(title=" 赤城 ", aliases=[" Akagi "])
    page = WikiPage.model_validate(values)
    assert page.title == "赤城"
    assert page.aliases == ["Akagi"]
    values["sources"].append(values["sources"][0].copy())
    with pytest.raises(ValidationError):
        WikiPage.model_validate(values)


@pytest.mark.parametrize(
    "updates",
    [
        {"snapshot_id": "not-a-snapshot-id"},
        {"source_id": " "},
        {"locator": " "},
        {"quote": " "},
        {"id": "invalid reference"},
        {"unexpected": "discarded evidence"},
    ],
)
def test_evidence_identifiers_and_locations_are_required(updates):
    values = metadata()
    values["sources"][0].update(updates)
    with pytest.raises(ValidationError):
        WikiPage.model_validate(values)


@pytest.mark.parametrize(
    "applicability",
    [
        {"scope": "historical_event"},
        {"scope": "historical_event", "event_id": "ship:akagi"},
        {"scope": "permanent", "event_id": "event:2024_summer"},
        {"scope": "unknown", "difficulties": ["甲", "甲"]},
        {"scope": "unknown", "stages": ["E-1", " E-1 "]},
        {"scope": "unknown", "valid_from": "2024-09-01", "valid_until": "2024-08-01"},
    ],
)
def test_applicability_cannot_hide_event_scope_or_reverse_dates(applicability):
    with pytest.raises(ValidationError):
        WikiPage.model_validate(metadata(applicability=applicability))


def test_historical_conditions_retain_dates_and_difficulty():
    page = WikiPage.model_validate(
        metadata(
            applicability={
                "scope": "historical_event",
                "event_id": "event:2024_summer",
                "valid_from": "2024-07-26",
                "valid_until": "2024-09-24",
                "difficulties": ["甲"],
                "stages": ["E-3"],
                "notes": "仅适用于该活动阶段",
            }
        )
    )
    assert page.applicability.valid_from == date(2024, 7, 26)
    assert page.applicability.difficulties == ["甲"]
    assert page.sources[0].snapshot_id == UUID(SNAPSHOT)


@pytest.mark.parametrize("field", ["valid_from", "valid_until"])
@pytest.mark.parametrize(
    "value",
    [0, "20240101", "2024-W01-1", "2024-01-01T00:00:00", datetime(2024, 1, 1)],
)
def test_applicability_dates_reject_timestamps_and_non_calendar_representations(
    field, value
):
    with pytest.raises(ValidationError):
        WikiPage.model_validate(
            metadata(applicability={"scope": "unknown", field: value})
        )


def test_applicability_accepts_native_calendar_dates_from_yaml():
    page = WikiPage.model_validate(
        metadata(applicability={"scope": "unknown", "valid_from": date(2024, 1, 1)})
    )
    assert page.applicability.valid_from == date(2024, 1, 1)


@pytest.mark.parametrize(
    "relations",
    [
        [{"target": "ship:akagi"}],
        [{"target": "ship:kaga"}, {"target": "ship:kaga"}],
        [{"target": "equipment:zero", "kind": "form_of"}],
        [
            {"target": "ship:akagi_base", "kind": "form_of"},
            {"target": "ship:akagi_kai", "kind": "form_of"},
        ],
    ],
)
def test_relations_cannot_be_self_referential_duplicate_or_ambiguous(relations):
    with pytest.raises(ValidationError):
        WikiPage.model_validate(metadata(relations=relations))


def test_remodels_are_distinct_pages_with_a_ship_parent():
    page = WikiPage.model_validate(
        metadata(
            id="ship:akagi_kai",
            title="赤城改",
            relations=[{"target": "ship:akagi", "kind": "form_of"}],
        )
    )
    assert page.relations[0].target == "ship:akagi"
    with pytest.raises(ValidationError):
        WikiPage.model_validate(
            metadata(
                id="equipment:zero",
                type="equipment",
                relations=[{"target": "ship:akagi", "kind": "form_of"}],
            )
        )


@pytest.mark.parametrize(
    "conflict",
    [
        {"summary": "数值冲突", "citations": ["c1"]},
        {"summary": "数值冲突", "citations": ["c1", "c1"]},
        {"summary": "数值冲突", "citations": ["c1", "missing"]},
        {"summary": "数值冲突", "citations": ["c1", "c2"], "status": "resolved"},
        {
            "summary": "数值冲突",
            "citations": ["c1", "c2"],
            "resolution": "未解决时不应隐藏结论",
        },
    ],
)
def test_conflicts_require_distinct_known_evidence_and_explicit_resolution(conflict):
    values = metadata(conflicts=[conflict])
    values["sources"].append(
        {**values["sources"][0], "id": "c2", "locator": "paragraph:2"}
    )
    with pytest.raises(ValidationError):
        WikiPage.model_validate(values)


def test_markdown_roundtrip_preserves_japanese_text_quotes_dates_and_snapshot_ids():
    values = metadata()
    values["sources"][0]["quote"] = "艦載機の搭載数: 18"
    values["applicability"]["valid_from"] = "2024-01-01"
    original = WikiDocument(
        metadata=WikiPage.model_validate(values), body="# 赤城\n\n原文の数値。[@c1]"
    )
    restored = parse_document(dump_document(original))
    assert restored.metadata == original.metadata
    assert restored.body == original.body


def test_frontmatter_accepts_utf8_bom_and_windows_line_endings():
    valid = dump_document(
        WikiDocument(metadata=WikiPage.model_validate(metadata()), body="# 赤城\n[@c1]")
    )
    restored = parse_document("\ufeff" + valid.replace("\n", "\r\n"))
    assert restored.metadata.title == "赤城"
    assert restored.body == "# 赤城\n[@c1]"


@pytest.mark.parametrize(
    "text",
    [
        "# 无 frontmatter",
        "---\n- unexpected\n- sequence\n---\n# Body",
        "---\ntitle: [unterminated\n---\n# Body",
        "---\ntitle: !!python/object:builtins.object {}\n---\n# Body",
        "---\nschema_version: '1'\n# missing closing delimiter",
    ],
)
def test_invalid_or_unsafe_frontmatter_is_rejected(text):
    with pytest.raises(ValueError):
        parse_document(text)


@pytest.mark.parametrize(
    ("original", "duplicate"),
    [
        ("\ntitle:", "\ntitle: first\ntitle:"),
        ("  scope: permanent", "  scope: permanent\n  scope: permanent"),
    ],
)
def test_duplicate_yaml_keys_cannot_silently_replace_valid_metadata(
    original, duplicate
):
    valid = dump_document(
        WikiDocument(metadata=WikiPage.model_validate(metadata()), body="# 赤城\n[@c1]")
    )
    assert original in valid
    with pytest.raises(ValueError, match="duplicate"):
        parse_document(valid.replace(original, duplicate, 1))
