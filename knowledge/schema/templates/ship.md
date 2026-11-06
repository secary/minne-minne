---
schema_version: "1"
id: "ship:<slug>"
type: ship
title: "<舰娘或改造形态标题>"
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

# <舰娘或改造形态标题>

## 概述

<说明舰种、日文名、中文名和本页对应形态，仅填入证据支持的事实。>[@c1]

## 形态与改造

<列出所属舰娘、改造关系、改造条件及出处。改造形态使用独立 ID，并在 relations 中声明 form_of。>

## 属性与装备

<保留属性、单位、等级条件、初始装备、装备限制和对应表格证据；区分本体与改造形态。>

## 获取方式

<说明建造、掉落、任务或活动获取条件；资料不足时明确待补证。>

## 关联任务

<使用稳定 ID 关联相关任务，并说明参与条件；尚无资料时注明待补证。>

## 适用条件与争议

<说明时期、阶段、难度和资料局限。无法解释的来源分歧写入 conflicts 并保留双方证据。>
