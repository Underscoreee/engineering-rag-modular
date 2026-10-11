# 真实 V2.4 提案样本：只读诊断

检查对象：`references/GB50010_2015_document.v2.4.partial.json`。本报告只统计和对照 JSON，未修改参考文件，也未重新阅读或 OCR 源 PDF。参考材料说明它来自一份 441 页扫描 PDF；这份 JSON 只能视为页面目录与有限人工核对区域。

| 项目 | 只读统计 |
|---|---:|
| `page_count` / 页面目录 | 441 / 441 |
| `content_extraction_status=not_processed` | 422 页 |
| 有 Block 的页面 | 19 页 |
| Block / 顶层 Table / Section | 29 / 3 / 13 |
| 正文 / 说明 Clause | 5 / 2 |
| Equation / `latex=null` | 10 / 2 |

该文件当前**不符合正式 V2.4**，主要原因：`schema_version="2.4-proposal"`；`FileRef.uri=null` 且含未在 `FileRef` 中定义的 `name`；processing 有正式模型未收录的人工审阅清单及字符串 warnings；表格和公式的状态值未映射到正式枚举；Equation 缺少 `equation_number_status`；说明 Clause `exp-4.1.5` 指向部分样本中不存在的正文 Clause。另有 `original_grid_available`、`mandatory_evidence`、`linked_clause_resolution_status`、`formula_numbers` 等提案元数据，需要保留在独立迁移记录中。

迁移必须显式进行，不能只替换版本号。尤其 `equation_number=null` 的真实无号公式与尚未识别编号的公式需要人工区分；模糊数值和关系符不得由脚本自动补正；`bbox_status=manual_approximate` 应继续标明人工估计。正式映射前提和待定字段见 [architecture-decisions.md](architecture-decisions.md)。
