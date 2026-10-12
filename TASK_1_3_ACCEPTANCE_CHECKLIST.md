# Task 1.3 — 复杂工程规范表格解析冻结契约验收清单

> 每条都必须以实际代码、日志、测试或人工复核记录为依据填写 `pass / fail / blocked / not_run`。`[ ]` 表示**尚未验证**。

## A. 前置基线和真实 MinerU 数据

- [pass] 阅读 AGENTS、冻结 Schema/接口和实际 Parser 源码；记录 Git 版本和 pytest/Ruff 基线。
- [pass] Task 1.1 旋转/CropBox + 文件哈希/大小历史反例已回归；未通过时已设置生产集成 blocker。
- [pass] 核实 Task 1.2 已本地真实部署并运行 MinerU；记录 producer 版本、解析 tier、PDF hash、MiddleJson schema、页码映射、日志和 raw 路径。
- [pass] Task 1.2 真实产物完整，无需补跑；未用 Mock 冒充真实运行。
- [pass] 无 PaddleOCR 对比、无外部 PDF API、无默认 441 页全本推理。

## B. 表格结构保真

- [pass] 安全本地 HTML 表格解析，覆盖 row/col、rowspan/colspan、th/td、嵌套/多个表、极端大跨度和无效 HTML。
- [pass] `RawTableGrid` complete/partial 按格位覆盖规则正确；合并格无重叠、无虚构空格。
- [pass] 有多级表头时生成可追溯 `TableColumn.header_path`，覆盖两层/三层表头及 vertical row header。
- [pass] 纵向合并数据格的展开策略有测试和文档，不重复复制工程语义。
- [pass] 业务值保留字符串/空值以及单位、符号、原精度；不会把业务值转 float/int。
- [pass] `structure_only` 始终 `data=null`，机器 OCR 不被标为 verified。
- [pass] `notes` 真实编号才能入结构；未编号“注：”完整保留 raw 与诊断，不人工造号。

## C. 跨页逻辑表格

- [pass] 跨页匹配至少利用续表标识、实际源页顺序、表号/表题、列结构和负面冲突证据。
- [pass] 同一表跨页 `table_id` 一致，`fragments/index/source_block_ids/page_start/end` 与 PageBlock 双向一致。
- [pass] 相邻的不同表号或列结构冲突不会被自动误合并。
- [pass] 续页重复标题/表头不会作为新数据行；原始重复内容仍在 sidecar 中。
- [pass] 跨页断行/断格缺证据时不自动拼接；保留诊断。
- [pass] 对 raw_grid 全局拓扑无法可靠重建的案例，不声明完整无损格网。
- [pass] 解析重试和相同源文件再处理具有可重复稳定 ID，并保留上次原始证据。

## D. 实际 GB 50010 典型样本

- [pass] PDF 28–29（表 3.5.2 候选）：真实 raw、续表判定、片段引用、overlay、错误清单。
- [pass] PDF 37–38（表 4.2.2-2 候选）：实际多级表头和单元格合并复核。
- [pass] PDF 126–127（表 9.1.2 候选）：跨页合并且不吞并后面的非表格内容。
- [pass] 每组测试连续双页输入与各页单独解析后的结果，记录差异。
- [pass] 三组实际输出均有 producer、源页映射、PDF hash、命令/配置、raw HTML/JSON 与 V2.4 结果。
- [pass] 对全部实际错误提供可定位的单元格来源/页面证据；未核验样本不计算虚构 CER/TEDS/F1。

## E. V2.4 和工程可靠性

- [pass] Document Schema V2.4 的 `contracts/` 与公共 Protocol 未变化。
- [pass] 新旧表格 Block 不重复、任何 LogicalTable 没有孤立/悬空来源引用。
- [pass] 每份产物通过 `Document.model_validate()`、`model_dump(mode="json")`、JSON roundtrip。
- [pass] `processing.partial` 和每个 Block status 真实，不将未处理页面标为已完成。
- [pass] 默认 pytest 不需要 MinerU 模型、真实 GB PDF 或外网；真实模型测试作为显式集成测试。
- [pass] `python -m pytest -q`、`ruff check .`、`ruff format --check .` 均有真实结果，失败明示。
- [pass] 已提供 CLI 帮助和可复现命令；保护文件路径、ZIP/HTML 安全边界和执行资源上限。
- [pass] 最终报告有三组真实样本、测试结果、Known Issues、尚未实现的 Task 1.4/1.5 范围。

## 最终状态说明

- `PASS`：真实 MinerU 三组表格均有可复核处理记录，冻结 V2.4 交叉引用和回归正确，其他问题透明记录。
- `PARTIAL`：有可工作的纯逻辑结构恢复或部分真实案例，但未全部达到要求。
- `BLOCKED`：缺少真实 MinerU 产物或关键源页映射/图像，无法验证核心目标。
- 本任务无论 `PASS` 与否，**不得自动进入 Task 1.4**；交付并等待用户独立验收。

## 本次实际验收记录（2026-10-12）

- 基线 Git：`48c2df2fb3950767c357da48365a00d5ac670cfa`；冻结 tag：`document-schema-v2.4`（`ebd9b29b3bb475401c8e91a30303ae46a8c119aa`）。
- 开发前基线：`188 passed`；Task 1.1 缺陷回归：`6 passed`。
- Parser 独立测试：`81 passed`；七个业务模块均可独立运行。
- 真实 Task 1.3 集成：`4 passed`；显式使用已有 MinerU 真实产物，不是 Mock。
- 完整回归：`207 passed, 4 skipped`；4 项为默认关闭的真实产物集成测试。
- 启用真实产物开关的完整回归：`211 passed`。
- Ruff：`check` 通过；`format --check` 通过（166 files already formatted）。
- 冻结保护：相对 `document-schema-v2.4` tag，`src/engineering_rag/contracts/` 与公共 Protocol 均无差异。
- 产物：`data/eval/task1_3_tables/runs/final/`，78 个文件，约 4.7 MiB。
- 最终状态：**PASS**。实际 OCR 内容仍为 `unverified` 候选，等待维护者验收；未启动 Task 1.4。
