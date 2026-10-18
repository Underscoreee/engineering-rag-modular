# Task 1.6 — 真实 GB 50010 质量评估与 Golden Dataset 方案

## A. 评估数据来源和状态

- 真实来源：《混凝土结构设计规范》GB 50010-2010（2015 年版），**原 PDF 物理页 1–441**；印刷页码不等于物理页码。
- 本包 `TASK_1_6_TEST_MATRIX.json` 继承已有 Task 1.2 的 **18 组候选、21 个物理页**（候选内容由前期人工观察和开发者测试重点确定，并非人工已验金标）。
- 固定测试源身份：`sha256=43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`、`size=154122112`、`page_count=441`；若用户项目里文件不同，应停止并确认，不以文件名相同视为同一来源。
- Task 1.5 的现有 `data/eval/task1_5_semantics/runs/final/GB-COMBINED/` 是**真实 MinerU 原始产物回放**，不等同于“本次全新 MinerU 推理”。

## B. 真实测试分层

| Layer | 页面/材料 | 目的 | 是否必须重新跑 MinerU |
|---|---|---|---|
| L0 单页烟测 | 16 | PDF IO、版面、1.0.x 条文、定位和 V2.4 | 必须（若环境阻塞需记录） |
| L1 语义回归 | 49–50、126–127、16+282 | 跨页条文、公式、续表、正文与说明 | 首先 replay，再有限 live 验证 |
| L2 元素专项 | 24、28–29、37–38、50、301 | LaTeX、多级表头、表注、符号解释 | 至少对有资源的场景 live |
| L3 代表覆盖 | 继承 18 组/21 页 | 页面类型分布、运行稳定性 | 经 Gate 0–2 通过后批次执行 |
| L4 全本 | 441 页、>=23 批（batch_size=20） | 稳定性和覆盖率 | **仅用户明确批准**，否则 NOT_RUN |

每次输出 `mode=live_mineru | replay_saved_raw | synthetic`，报告中单独计数，不能混入一个代表“模型本次推理总页数”的指标。

## C. Golden 标注设计（只收已核验数据）

建议从 8–12 个高价值物理页起步人工标注（优先 16、24、28、29、37、38、50、126、127、282、301）。批次规划可处理更多页，不表示更多金标。

建议标注记录最少包含：

```json
{
  "item_id": "candidate-p050-formula-6.2.1-1",
  "physical_page": 50,
  "source_sha256": "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682",
  "label_type": "formula_condition",
  "source_bbox_pdf_points": null,
  "label": "当 ε_c ≤ ε_0 时",
  "label_status": "candidate_pending_human_review",
  "reviewer": null,
  "reviewed_at": null,
  "dataset_version": null,
  "source_evidence": "scanned_pdf_page_50"
}
```

该条仍是**候选模板**，不是经过人审的结论。坐标不能自动猜；审核后注明标注人员、日期、裁剪图及坐标证据；没有审核签名/版本的结果不可计入准确率。可以先搭建简单 JSONL 标注、校验与导出工具，但无需额外前端产品。

标注对象：页类型、文本及阅读顺序、Block 坐标/类别、表格源/rowspan/colspan/header_path/单元格值/跨页归属、Formula LaTeX/编号/条件/共享解释、Section/Clause 边界与归属、正文/条文说明链接、字段完整性。

## D. 指标和定义

| 领域 | 建议指标 | 分母与注意事项 |
|---|---|---|
| 页面类型 | 每类 P/R/F1、macro-F1，unknown 混淆 | **人工核验**的页面数；未知类别单独报告 |
| OCR | Character Error Rate `CER=(S+D+I)/N` | 已标注原文的真实字符数；关系符号/上下标另列错例 |
| 阅读顺序 | pairwise order accuracy | 已标注有序 Block 对数，页面脚注可单独分类 |
| Layout | Block detection P/R/F1，bbox IoU | 人工标注块、预定义 IoU 阈值和一对一匹配 |
| 表格 | grid 结构匹配率、续表 Precision/Recall/F1、表注覆盖率 | 人工标注的表格、cell、跨页关系总数 |
| 公式 | 检测召回、印刷编号准确率、归一化 LaTeX 匹配、人工等价率 | 人工标注公式数；自动等价不能替代人审 |
| 公式条件 | 条件引用 precision/recall、错误串号数、重复正文数 | 已标注的条件→formula_id 对数 |
| 符号解释 | symbol→group coverage、完整性、重复率/漏消费 | 已标注符号解释条数；跨页截断单独报告 |
| Clause | 编号/起止边界 P/R/F1，跨页覆盖，Body/Explanation 分类 | 已标注 Clause，不能把单页数条当成条文数量 |
| 来源 | 物理页、source_block、table/fragments、ID 一致性率 | 已处理输出中的所有引用；任何污染硬失败 |
| 性能 | wall time/page、P50/P95、峰值内存、GPU/CPU、输出字节 | 有明确任务粒度和测量来源，避免平均不同机器 |
| 运行可靠性 | 成功 / 失败 / 未处理 / 阻塞页数、重试成功率 | 从运行 Manifest 的真实状态计数，非金标准确率 |

**评估硬规则**：`sample_count=0` 的指标状态必须是 `not_evaluated`，不产生假 0 或假 1；所有百分比打印 `N/M` 和对应物理页面集合。分页和角色不一致时要标明该结果不是同一标注基准。

## E. 错误分类与人工验收

推荐 `error_catalog.json` 分类：

- `ocr_character`、`ocr_operator_semantic`、`layout_missing`、`wrong_reading_order`、`bbox_geometry`
- `table_cell`、`table_header`、`table_continuation`、`table_clause_boundary`
- `formula_latex`、`formula_number`、`formula_condition`、`formula_explanation`、`formula_duplicate`
- `section_tree`、`clause_boundary`、`clause_page_zone`、`explanation_link`
- `source_identity`、`unresolved_pending`、`partial_extraction`、`resource_timeout`、`artifact_corrupt`

每个错误记录 `physical_pages`、`source_block_ids/formula_ids/table_ids`、引擎/解析器版本、原始片段、诊断、人工核验状态和建议修复位置。

**允许 `PASS` 的技术验收不等于“工程规范语义准确率已达到生产要求”**。若金标数量不足或复杂案例明显错误，最终报告应同时给出工程管线是否达标、质量是否达标两个独立结论。
