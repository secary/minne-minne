---
schema_version: "1"
id: "quest:<slug>"
type: quest
title: "<任务标题>"
aliases: []
sources:
  - id: c1
    source_id: "<来源稳定 ID>"
    snapshot_id: "<raw_snapshots.id 的 UUID>"
    locator: "<具体段落或表格定位标识>"
relations: []
applicability:
  scope: unknown
  difficulties: []
  stages: []
  notes: "<确认常驻或历史适用范围后更新>"
conflicts: []
---

# <任务标题>

## 概述

<说明任务编号、日文名、中文名和周期；编号可加入 aliases 供精确检索。>[@c1]

## 任务条件

<保留编成、旗舰、海域、胜利等级、次数等条件，不能在摘要中省略限制。>

## 前置与后续

<使用稳定 ID 关联前置与后续任务，分别用 requires 或 unlocks 声明有方向的关系。>

## 奖励

<列出固定奖励与选择奖励，保留数量、单位和选择组关系，并注明证据。>

## 适用条件与争议

<说明任务开放时期、更新情况、条件争议和待补证信息。>
