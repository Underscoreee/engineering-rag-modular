# Task 1.5 验收清单 — Section、Clause 与条文说明（Document V2.4 Frozen）

> 状态：**已执行，结论 PARTIAL**。实现与测试门槛通过；页 301 缺少前置 4.1 Section 页面，相关候选按保守策略 pending。证据见 `TASK_1_5_IMPLEMENTATION_REPORT.md` 与 `data/eval/task1_5_semantics/runs/final/GB-COMBINED/`。

## A. 前置与安全

- [x] 阅读 `AGENTS.md`、真实 contracts 源码、冻结记录，确认 `2.4` Frozen，未修改任何公共 Pydantic/Protocol。
- [x] 确认 Task 1.4 最新语义组修复代码和原生 MinerU 原始产物存在，并通过真实回归。
- [x] 检查 Task 1.1 旋转/CropBox/源文件 SHA256/size_bytes 历史缺陷修复状态。
- [x] 记录 GB 50010 PDF SHA256、物理页码、MinerU 模型/版本、原始 JSON Schema、运行/重放命令。

## B. 页面与章节识别

- [x] 仅在证据足够时填 `body` / `explanation_body`；277 条文说明封面不是 Clause 页面，未知页不编造。
- [x] 已加载真实章、节与说明树正确，两个 content_group 的 section_id 与 tree 隔离。
- [x] `structure_path`、parent_id、section number 严格一致，无悬空引用/环。
- [x] 目录章节名不创建正文 Sections；未能确定的标题记 sidecar。

## C. Clause 边界及跨页

- [x] 第 16 页提取至少可证实的独立条文及来源，不从页脚/目录编造条文。
- [x] 第 49–50 页：`6.2.1` 跨页，50 页分项 2～5 不当独立条文；仅第 50 页解析不虚构条文起点。
- [x] 第 126–127 页：跨页逻辑表可归属原 Clause，表后的 `9.1.3` 不被吞并。
- [x] 同一 PageBlock 含多个条文时，只有拿到可靠 span/bbox 才拆分；保留 old/new ID 和 source 消耗记录。
- [x] 正文、条文说明同号独立 clause_id；已存在正文时说明 `explains_clause_id` 准确，否则 null + pending。

## D. ContentUnit 与 plain_text

- [x] body/list_item/table/formula/image 类型映射合法，`order` 唯一有序。
- [x] `Clause.source_block_ids` 严格与 units 累积来源一致。
- [x] Table Unit 引用全部碎片；Formula Unit 引用真实 IDs，组级共同解释不重复。
- [x] 第 50 页两个公式适用条件、七条公式和共享说明保留，消除了重复 Body 输出。
- [x] 若导出 plain_text，只调用冻结 renderer 并写完整 version/digest；来源不足则三项 null。
- [x] 不确定 OCR/边界仅生成 partial + 诊断；不编造标题、文字、分页或公式。

## E. 强制性证据与来源溯源

- [x] 不基于“应/必须/严禁”或字重判强条；无权威核验 `is_mandatory=null`。
- [x] Pending 证据独立存 sidecar；未制造 Verified 强条证据。
- [x] 每一个输出 Clause、Section、Unit 可以追溯 PDF 物理页和对应原始 block/span/bbox。
- [x] 原始 MinerU 输出和已经生成的 Task 1.2–1.4 产物保留，不覆盖历史；来源重复消费和 ID lineage 有可重放证据。

## F. 代码测试与真实评估

- [x] 配置文件 S01～S36 合成正反案例通过，覆盖 unknown/pending/idempotence 和悬空引用防护。
- [x] 第 16、49–50、126–127、277/282、301 页真实集成产物生成；页 301 缺父 Section 明确标注 PARTIAL。
- [x] `Document.model_validate()`、JSON round-trip、页面引用、Section/Clause 验证全部通过。
- [x] 完整 pytest、`ruff check .`、`ruff format --check .` 均实际运行并通过。
- [x] 测试包含不依赖真实 MinerU 环境的离线 Fixture Replay；真实测试来自真正 MinerU 原始结果。
- [x] `TASK_1_5_IMPLEMENTATION_REPORT.md` 包括每项真实结果、歧义及后续风险，结论 PARTIAL。
- [x] Task 1.5 结束后停止，不自行进入 Task 1.6、Chunking 或其它业务模块。

## 验收判定

- **PASS**：冻结契约未变，真实来源可验证，关键真实案例与合成回归全部通过，主要边界没有未解释的信息丢失。
- **PARTIAL**：代码与合成测试完成，但部分真实页、上游公式修复、Min­erU 环境或数据尚不足，明确剩余工作。
- **BLOCKED**：无法合法构建 Clause/跨引用，依赖缺失或重大来源完整性风险未解决。不得以单纯 `pytest passed` 代替真实集成通过。
