---
schema_version: "1"
id: "event:<slug>"
type: event
title: "<活动标题>"
aliases: []
sources:
  - id: c1
    source_id: "<来源稳定 ID>"
    snapshot_id: "<raw_snapshots.id 的 UUID>"
    locator: "<具体段落或表格定位标识>"
relations: []
applicability:
  scope: historical_event
  event_id: "event:<slug>"
  difficulties: []
  stages: []
  notes: "<填写活动时间及已确认的历史适用范围>"
conflicts: []
---

# <活动标题>

## 概述

<说明活动名称、所属时期和本页范围。>[@c1]

## 时间与阶段

<列出开放与结束时间、前后段或阶段划分，保留时区和来源；不要用抓取时间代替活动时间。>

## 难度与规则

<按难度和阶段说明规则、限制、奖励及特例，区分已证实内容与推测。>

## 海域与攻略

<使用稳定 ID 关联各活动海域和机制；历史攻略应保留原有适用条件。>

## 历史适用范围与争议

<说明本页为历史资料，记录范围、来源局限与未解决分歧，避免把历史活动特例推广为常驻机制。>
