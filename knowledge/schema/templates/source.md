---
schema_version: "1"
id: "source:<slug>"
type: source
title: "<来源摘要标题>"
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
  notes: "<依据资料内容填写结论适用范围，不使用抓取日期代替>"
conflicts: []
---

# <来源摘要标题>

## 来源概述

<说明资料出处、原页面主题和摘要范围；通过 sources 绑定不可变快照及具体位置。>[@c1]

## 资料范围

<说明涉及实体、机制、时期、难度和阶段；来源修订时间与抓取时间由快照元数据保留。>

## 关键事实

<按证据概括事实，保留数值、单位、公式前提和限制，逐项使用本页引用标签。>

## 关联页面

<使用稳定 ID 链接由本资料支持的舰娘、装备、机制、任务、海域或活动页面。>

## 局限与待确认

<说明缺失信息、推测、来源偏差和与其他资料的分歧；冲突保留各自证据。>
