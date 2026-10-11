# 架构决策记录

## ADR-001：模块化单体（已接受）

一个安装包与部署单元，模块以 Python Protocol + Pydantic 契约进程内协作；不使用 HTTP/gRPC 微服务。

## ADR-002：从零开始且 Task 0 只建边界（已接受）

不迁移 Task 1～5，不提供业务伪实现。当前只交付 Schema、Protocol、骨架、文档与测试。

## ADR-003：双视图 Document 与外置关系校验（已接受）

Document 同时保存页面布局和语义结构。局部约束在 Pydantic 中验证，跨 ID 引用由纯函数验证，避免构造模型时访问外部状态。

## ADR-004：显式检索分数语义（已接受）

结果携带来源/分数类型；加权融合要求先归一化且权重和为 1，RRF 不接受原始分数权重。

## ADR-005：Document Schema V2.4（已接受，Task 0.1）

`Document` 固定版本 `2.4`。页面采用 `page_type`、五类 PageBlock 及文档级 bbox 坐标约定；逻辑表格统一存入顶层 `tables[]`，所有物理 table Block 通过 `table_id` 引用。公式有唯一 `formula_id`，印刷编号通过 `equation_number_status` 明确有号、确认无号和尚未识别三态。正文与说明按 `clauses.normative/explanations` 分组，Clause 和 Section 保留各自 ID 与来源。Document 构造时调用纯引用校验函数，partial 数据只放宽尚未声明的内容，已声明引用不放宽。

`processing.partial` 描述整体结构化结果是否完整，`is_complete_document_ocr` 单独描述 OCR 范围；完整 OCR 后仍可因语义结构未完成而 `partial=true`。只有 `partial=false` 才要求页清单齐全、全部页面 complete 且 OCR 完成。

本决策与 `AGENTS.md` 旧条款“印刷页码/页标签是另外的字段”存在范围差异：V2.4 明确删除 `printed_page_label`。Task 0.1 只把 `AGENTS.md` 当前阶段改为 0.1，不改长期条款；按本任务较高优先级的已确认产品决策执行，后续若需统一顶层规范，应另行获批。

## ADR-006：真实 441 页提案样本的只读迁移边界（已接受）

`references/GB50010_2015_document.v2.4.partial.json` 保持原样：441 页物理目录，422 页 `not_processed`，仅 19 页有人工转录 Block；不是完整 OCR 文档。`2.4-proposal` 不由模型自动转换为 `2.4`。若以后派生正式样本，必须在独立文件中逐项处理并保存来源和迁移记录：

| 提案字段或状态 | 正式 V2.4 的处理前提 |
|---|---|
| `schema_version="2.4-proposal"` | 只有完成其余字段与引用核验后，才在派生文件中写 `"2.4"` |
| `source_file.uri=null`、额外 `name` | `FileRef` 原契约要求真实非空 URI；由文件目录/存储方提供可验证 URI，文件名作为外部迁移元数据保留，不能编造 URI |
| `processing` 的页号清单、提取策略、`pdf_has_text_layer`、字符串 warnings | 保留在独立证据/迁移记录；正式 warnings 转为 `ContractError` 时应人工分类，不静默丢失 |
| 提案中的长文本 `extraction_status`、`recognition_status`、`transcription_status` | 逐条核对后映射至正式枚举；模糊单元格保留为 `unverified` 并带 warning，不升级为 `verified` |
| `original_grid_available` | 仅迁移记录中保留；`raw_grid` 设计尚未确定 |
| `is_explanation`、`mandatory_evidence`、`linked_clause_resolution_status`、`formula_numbers` | 前者由 Clause 分组表达；其余作为待决元数据记录。`exp-4.1.5` 指向未在部分样本内声明的正文 Clause，正式模型需保持 `explains_clause_id=null` 并在迁移记录保存待解析目标，不能造一个正文 Clause |
| 公式 `equation_number=null` 或未转录公式 | 人工区分 `confirmed_absent` 与 `unknown`；完整公式才可 `verified`，未转录保留 `latex=null` |

参考样本中的 `bbox_status=manual_approximate` 必须原样保留其质量含义；对有争议的规范数字或关系符不得自动“校正”。Task 0.1 只做只读结构诊断，没有生成派生真实样本。

## 待决定

- 各实现稳定 ID 的具体生成规范（内容哈希、命名空间 UUID 或持久化分配）。
- 部分解析的 artifact 存储格式及版本迁移机制。
- 后续首次单模块实现采用的 PDF 库与评估数据集；决定前不得写入公共契约。
- `raw_grid` 是否引入，以及如何表达合并单元格的无损格网。
- 除表格以外，content unit 中正文/公式副本是否删除，以及 `plain_text` 是否继续保存。
- `mandatory_evidence` 的结构、来源分类与判定规则。
- `structure_path`、`processing` 和 asset 版本信息等字段后续是否精简。
