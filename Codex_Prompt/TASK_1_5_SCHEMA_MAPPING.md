# Task 1.5 — MinerU → V2.4 Section / Clause 精确映射与示例

> 以仓库的冻结 `contracts/documents.py` 为准。以下 JSON 仅是**局部字段形态演示**，不是完整、可直接经 `Document.model_validate` 的实例；不得硬编码演示 ID，也不得假装这些示例是 OCR 实测。

## 1. 私有来源与公共对象

| 原始/内部候选 | 冻结 V2.4 位置 | 注意事项 |
|---|---|---|
| 页面类别候选 | `Page.page_type` + `page_type_basis` | `body` 或 `explanation_body` 才可承载相应 Clause；无可靠证据为 `unknown` |
| 章/节题头 | `Document.sections[]` | public Section 无 bbox、page：放私有来源 sidecar |
| 条文起点及延续 | `clauses.normative[]` / `clauses.explanations[]` | 分项序号不得新建 Clause |
| 普通文本 | `ClauseContentUnit(content_type="body")` | 引用原有 Body Block，不在 ContentUnit 冗余 OCR 文本 |
| `1` / `2` / `（1）` 分项 | `content_type="list_item"`, `list_item_label` | source Block 必须为 Body，不和 Clause 号码混淆 |
| 跨页表 | `content_type="table"`, `table_id`, 完整 `source_block_ids[]` | 覆盖所有 fragments；未知归属留 pending |
| 组级多公式 | `content_type="formula"`, `formula_ids[]`, `source_block_ids[]` | 一组五式可以同一 source Block + 五个 formula_id；条件、释义不重复 |
| 图片 | `content_type="image"`, `asset_id` | 必须有真实 source Block 和 asset |
| 说明条文 → 正文条文 | `explanation.explains_clause_id` | 正文不存在时设 null + sidecar pending，不允许 dangling ref |
| 强条候选 | `is_mandatory=null`, `mandatory_evidence=[]` + 私有候选 | 仅核验充分才能写明确判断 |
| 可检索文本 | `ClauseContent.plain_text`, `_renderer_version`, `_source_digest` | 必须由冻结 renderer 派生；证据不全时保持 null |

## 2. 同号正文与说明是不同实体

假设 PDF 扫描结果**经可靠识别**出现 `1.0.1`：

```json
{
  "sections": [
    {"section_id": "sec-norm-1", "number": "1", "title": "总则", "section_type": "chapter", "content_group": "normative", "parent_section_id": null, "structure_path": ["1"]},
    {"section_id": "sec-expl-1", "number": "1", "title": "总则", "section_type": "explanation", "content_group": "explanation", "parent_section_id": null, "structure_path": ["1"]}
  ],
  "clauses": {
    "normative": [{"clause_id": "clause-norm-1.0.1", "clause_number": "1.0.1", "section_id": "sec-norm-1", "source_block_ids": ["block-body-001"], "is_mandatory": null, "mandatory_evidence": [], "explains_clause_id": null}],
    "explanations": [{"clause_id": "clause-expl-1.0.1", "clause_number": "1.0.1", "section_id": "sec-expl-1", "source_block_ids": ["block-expl-001"], "is_mandatory": null, "mandatory_evidence": [], "explains_clause_id": "clause-norm-1.0.1"}]
  }
}
```

上面 Clause 省略了 `clause_content`, `page_start`, `page_end` 等必需字段，专为说明关联逻辑，不能当有效 V2.4 文档。**若只加载第 282 页，没有正文 1.0.1，则 `explains_clause_id` 必须为 null。**

## 3. 第 49–50 页的正确关系

```text
Section "6"（正文 chapter）
  └── Section "6.2"（正文 section）
       └── Clause "6.2.1"
            ├── body：49 页主条文和首项等
            ├── list_item：50 页的 “2 ...”
            ├── list_item：50 页的 “3 ...”
            ├── formula：第 50 页第 1 组（6.2.1-1 ~ 6.2.1-5）
            ├── list_item：50 页的 “4 ...”
            ├── list_item：50 页的 “5 ...”
            └── formula：第 50 页第 2 组（6.2.1-6 ~ 6.2.1-7）
```

- “当……时”条件已归入公式组，与该组同一语义来源，**不得再作为 list_item/body 重复**。
- 公式符号解释由 Group 所有，**不得再次当 body Unit 渲染**。
- 第 50 页局部没有 Clause 开始信息时应该是 orphan，直到第 49 页提供证据；此树**是期望结构而非已经实测确认**。

## 4. 断点和合法性陷阱

1. `ClauseContentUnit.order` 唯一、递增。
2. `Clause.source_block_ids` 需严格等于所有 units 的 source block 按顺序去重串联；不能遗漏分页片段或重复堆积。
3. `table` unit 必须包含 table 所有 `fragments` 的 block IDs；即使表后已经开始 `9.1.3`，也不能吞并新条文。
4. `formula` unit 的 `formula_ids` 必须来自其 source formula Block 的 `FormulaGroup`；组级说明仅渲染一次。
5. Clause 页范围需覆盖所有来源 Block 的物理页；如果来源落 `unknown` 页类型，则不能导出对应 Clause。
6. Section `structure_path` 必须延续合法父结构，末级等于 `number`。
7. `plain_text` 缓存不可手写或部分填；要么三元组全为 null，要么从冻结 renderer 得到 text/digest/version。
8. **没有证据则不建对象**，特别是目录/公告/说明封面、OCR 误识的条文号和强条状态。
9. 修正 OCR 导致旧 Block 需要拆分时，记录 old→new IDs 和消耗范围，预先更新引用；不允许悬空引用。
10. 仅使用已授权可本地处理的规范 PDF，不能上传至外部服务。
