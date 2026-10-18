# Task 1.6 技术设计 — 可恢复的 MinerU → Frozen V2.4 管线

本设计是 Parser 模块私有的**目标架构**；实施时先复用现有实现，不应为匹配示意目录而无谓重构。

## 1. 数据流和阶段标识

```text
PDF 原始文件（sha256 + page_count + standard identity）
      │
      ├── SourcePreflight（FileStore/read/PyMuPDF，保留源物理页）
      ▼
BatchPlanner  (当前 max_selected_pages=20，按连续页与续表组优先)
      ▼
LocalMinerURunner  ── raw middle_json / markdown / figures / run logs
      ▼
Private Normalizer + V2.4 candidate adapter
      ├── Tables / cross-page fragments / raw_grid
      ├── Formulas / equation_number / context / symbols / dedup
      └── Page classification / sections / normative + explanation clauses
      ▼
StrictSourceMerger（源身份 + 版本 + page/ID conflict + pending）
      ▼
Document.model_validate_json + integrity checks
      ├── final partial Document
      ├── provenance sidecars / unknown pending
      ├── overlays + error catalog
      ├── evaluation annotations / metrics
      └── atomic batch checkpoints / run manifest
```

**注意**：在批次全部解析完成之前，不能把缺少上一页条文/续表尾部的局部解释误标为完整。同一个逻辑文件跨批次必须合并来源视图后执行领域语义组装，或设计等价的补充上下文重关联算法并用反例证明可靠。

## 2. 三种运行证据严格分离

| mode | 依据 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| `live_mineru` | 实际 MinerU 进程+模型推理日志+原始产物 | 当前版本在本机运行了真实扫描 PDF | 人工金标准确率、全本 441 页精度 |
| `replay_saved_raw` | 已保存、哈希检验通过的历史真实 MinerU 输出 | 后处理可重放、幂等性、V2.4 契约 | 本轮重新完成模型推理 |
| `synthetic` | 构造 JSON、模拟故障 | 合并和容错的确定性行为 | 真实视觉识别质量 |

每个批次 `mode`、输入、版本、物理页、elapsed、errors、原始产物哈希均落盘，跨模式数据禁止混用在同一份声称“全本 live”的报告中。

## 3. 批次规划策略

- 兼容现有 `ParseConfig.options`（字符串、整数、浮点、布尔），如 `page_selection="16,28-29,49-50"`、`document_engine="mineru"`。
- 编排层接收 21 页代表集和 `batch_size <= max_selected_pages=20`，输出多个有序、确定性 batch；默认单并发避免 WSL OOM。
- 尽量保持 `28–29`、`37–38`、`49–50`、`126–127` 同批，以确保解析时完整上下文；如果确实跨批，则 pending 有机器可读可恢复语义关系。
- 在最后统一执行第 1.5 阶段的 global classification/semantic assembly；不合格或没有上下文的页面维持 unknown/pending。
- 如果用户明确发起全本 441 页，遵守相同批策略，并先呈报至少预估批数（当 batch_size=20 时至少 23 批）及 WSL 磁盘、超时、显存限制。

## 4. Manifest / Checkpoint 不替代公共 Schema

Parser 内部 `RunManifest` 建议字段：

```json
{
  "run_id": "example-not-actual-run",
  "run_status": "planned",
  "source": {"sha256": "<sha256>", "page_count": 441, "standard_code": "GB 50010-2010", "edition": "2015年版"},
  "schema_version": "2.4",
  "parser_version": "<runtime-recorded>",
  "mineru_version": "<runtime-recorded>",
  "model_signature": "<runtime-recorded>",
  "mode": "live_mineru",
  "batches": [{"batch_id": "b0001", "physical_pages": [16], "status": "planned", "attempts": 0}],
  "outputs": {},
  "golden_dataset_version": null
}
```

上述是**Parser 私有示例而不是新公共契约**。生产实现要校验 manifest schema、约束路径不得逃逸运行目录、引用的真实文件 hash 与 bytes 匹配，原子保存并防止断电损坏。

恢复规则：`succeeded` 批次只有在 PDF 身份、选页、参数、引擎/模型版本和输出 hash 全部匹配时才可复用；失效必须重跑而非跳过。`failed` 可显式 retry；`running` 中断后需转换为可恢复状态并保留错误证据。

## 5. 保证真正可信的语义完整性

- 原页面 OCR 完整保留在 raw sidecar；最终 Document 禁止将已完全消费的公式适用条件/符号解释复制为独立 Body。
- 某条 `Equation` 即使被组合到一个 FormulaGroup，也保留独立 `formula_id`、印刷编号及来源；**共享 `symbol_explanations` 只保留在组级**。
- 页面 50 检验 `6.2.1-1` 的 `ε_c ≤ ε_0`（曾误认成 `\\ll`）和 `6.2.1-2` 的适用范围，以及第 301 页编号未知/已核实无编号的区别。
- 跨页 Table 的页片段与一个 LogicalTable 互相引用，表 9.1.2 之后 Clause 9.1.3 不得吞入续表。
- 含跨页说明或尚未解析完的符号描述，不得标完整；未知 page_type 残留 source block 进入 pending。
- `plain_text` 来源于权威 PageBlock/LogicalTable/FormulaGroup 渲染且经过版本/hash 一致性验证；不能把重复数据写两份缓存。
- 强条判定证据只来自有审查记录的权威来源；无核验保持 null。

## 6. 数据量与部署约束

- 真实文件为图像扫描 PDF，441 页、154122112 字节、SHA-256：`43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682`（本次工具环境重新计算核对，用户实际项目必须独立重算）。
- 不应把 PDF 本体、OCR 大型原始产物、模型权重提交 Git；小型匿名化或用户批准的脱敏示例可入库。
- 输出应分为轻量 Git 版本化源码/报告，以及独立本地运行目录的原始大产物。
- 原始 PDF 输入、MinerU ZIP、HTML、图片均为不可信源，控制路径、大小及压缩包解压上限，禁用外部执行和意外外传。
