"""Schema v1 for Wiki frontmatter, independent of storage and LLM providers."""

import re
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1"
PAGE_ID_PATTERN = (
    r"^(ship|equipment|mechanic|quest|map|event|source):[a-z0-9][a-z0-9_-]*$"
)
PageId = Annotated[str, StringConstraints(pattern=PAGE_ID_PATTERN, max_length=128)]
CitationId = Annotated[
    str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)
]
Text = Annotated[str, StringConstraints(min_length=1)]


class PageType(StrEnum):
    SHIP = "ship"
    EQUIPMENT = "equipment"
    MECHANIC = "mechanic"
    QUEST = "quest"
    MAP = "map"
    EVENT = "event"
    SOURCE = "source"


PAGE_DIRECTORIES = {
    PageType.SHIP: "ships",
    PageType.EQUIPMENT: "equipment",
    PageType.MECHANIC: "mechanics",
    PageType.QUEST: "quests",
    PageType.MAP: "maps",
    PageType.EVENT: "events",
    PageType.SOURCE: "sources",
}
PAGE_SECTIONS = {
    PageType.SHIP: (
        "概述",
        "形态与改造",
        "属性与装备",
        "获取方式",
        "关联任务",
        "适用条件与争议",
    ),
    PageType.EQUIPMENT: (
        "概述",
        "属性与适用条件",
        "获取与改修",
        "关联舰娘与任务",
        "适用条件与争议",
    ),
    PageType.MECHANIC: ("概述", "规则与计算", "适用条件", "示例与边界", "争议与待确认"),
    PageType.QUEST: ("概述", "任务条件", "前置与后续", "奖励", "适用条件与争议"),
    PageType.MAP: (
        "概述",
        "路线与条件",
        "敌编成与攻略",
        "掉落与统计条件",
        "适用条件与争议",
    ),
    PageType.EVENT: (
        "概述",
        "时间与阶段",
        "难度与规则",
        "海域与攻略",
        "历史适用范围与争议",
    ),
    PageType.SOURCE: ("来源概述", "资料范围", "关键事实", "关联页面", "局限与待确认"),
}


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _unique(values: list, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


class Citation(SchemaModel):
    id: CitationId
    source_id: Text
    snapshot_id: UUID
    locator: Text
    quote: Text | None = None


class EvidenceRecord(SchemaModel):
    """An externally supplied inventory; not proof that a claim is supported."""

    source_id: Text
    locators: list[Text] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_locators(self) -> Self:
        _unique(self.locators, "evidence locator")
        return self


class Relation(SchemaModel):
    target: PageId
    kind: Literal["related", "form_of", "requires", "unlocks", "obtained_from"] = (
        "related"
    )


class Applicability(SchemaModel):
    scope: Literal["permanent", "historical_event", "unknown"]
    event_id: (
        Annotated[
            str,
            StringConstraints(pattern=r"^event:[a-z0-9][a-z0-9_-]*$", max_length=128),
        ]
        | None
    ) = None
    valid_from: date | None = None
    valid_until: date | None = None
    difficulties: list[Text] = Field(default_factory=list)
    stages: list[Text] = Field(default_factory=list)
    notes: Text | None = None

    @field_validator("valid_from", "valid_until", mode="before")
    @classmethod
    def date_only(cls, value):
        if value is None or type(value) is date:
            return value
        if isinstance(value, str) and re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value
        ):
            return value
        raise ValueError("applicability dates must use YYYY-MM-DD without a time")

    @model_validator(mode="after")
    def consistent_scope(self) -> Self:
        if self.scope == "historical_event" and not self.event_id:
            raise ValueError("historical_event scope requires event_id")
        if self.scope == "permanent" and self.event_id:
            raise ValueError("permanent scope cannot specify event_id")
        if self.valid_from and self.valid_until and self.valid_from > self.valid_until:
            raise ValueError("valid_until must not precede valid_from")
        _unique(self.difficulties, "difficulty")
        _unique(self.stages, "stage")
        return self


class Conflict(SchemaModel):
    summary: Text
    citations: list[CitationId] = Field(min_length=2)
    status: Literal["unresolved", "resolved"] = "unresolved"
    resolution: Text | None = None

    @model_validator(mode="after")
    def consistent_resolution(self) -> Self:
        _unique(self.citations, "conflict citation")
        if self.status == "resolved" and not self.resolution:
            raise ValueError("resolved conflict requires resolution")
        if self.status == "unresolved" and self.resolution:
            raise ValueError("unresolved conflict cannot specify resolution")
        return self


class WikiPage(SchemaModel):
    schema_version: Literal["1"]
    id: PageId
    type: PageType
    title: Text
    aliases: list[Text] = Field(default_factory=list)
    sources: list[Citation] = Field(min_length=1)
    relations: list[Relation] = Field(default_factory=list)
    applicability: Applicability
    conflicts: list[Conflict] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_page(self) -> Self:
        if self.id.split(":", 1)[0] != self.type:
            raise ValueError("page id prefix must match type")
        _unique([self.title.casefold(), *(a.casefold() for a in self.aliases)], "alias")
        _unique([source.id for source in self.sources], "citation id")
        _unique(
            [(s.source_id, s.snapshot_id, s.locator) for s in self.sources],
            "source evidence",
        )
        _unique([(r.kind, r.target) for r in self.relations], "relation")
        forms = [r for r in self.relations if r.kind == "form_of"]
        if len(forms) > 1:
            raise ValueError("a ship form can have only one form_of relation")
        for relation in self.relations:
            if relation.target == self.id:
                raise ValueError("relation cannot target the page itself")
            if relation.kind == "form_of" and (
                self.type != PageType.SHIP or not relation.target.startswith("ship:")
            ):
                raise ValueError("form_of must link ship pages")
        known = {source.id for source in self.sources}
        for conflict in self.conflicts:
            if not set(conflict.citations) <= known:
                raise ValueError("conflict references undefined citation")
        return self
