# Architecture Task 1.6 — Document Parser 全链路集成、质量评估与最终优化（Codex 执行任务书）

> **项目**：Engineering RAG / 工程规范 RAG  
> **本阶段**：Task 1.6（Task 1 最终集成和验收）  
> **解析路线**：本地 MinerU（不进行 PaddleOCR 对比选型） + 工程规范语义后处理  
> **公共契约**：Document Schema **V2.4 — FROZEN**，不得变更 `contracts/` 的模型、Protocol、字段及业务语义  
> **重要说明**：本文件是待执行的工程任务，不代表已完成真实推理、人工金标或 441 页全本验收。

## 0. 工作边界与执行方式

你是该项目的 Python 架构和文档解析工程师。请先审计当前仓库的真实状态，再决定如何实现，严禁无证据宣称前置 Task 已通过。所有新业务逻辑应封装在 `modules/document_parser/internal/` 或独立 Parser 测试/脚本中；不实现 Chunking、Embedding、向量数据库、检索或 LLM 生成。

本阶段必须依次通过以下门禁，不允许一上来对 441 页直接运行大模型：

1. **Gate 0：Task 1.5 前置缺陷核验并修复**。
2. **Gate 1：真实 MinerU + V2.4 端到端代表页运行**。
3. **Gate 2：批次合并、检查点、恢复和数据来源校验**。
4. **Gate 3：Golden Dataset 核验流程与有分母的质量评估**。
5. **Gate 4：资源、性能、失败注入与总体交付验收**。

执行每一阶段都要保存真实命令、运行环境、日志、成功和失败状态。若 GPU/模型/金标缺失，可以完成不依赖它们的阶段，但不得用 Mock 冒充真实推理，不得把“部分通过”写成“全部 PASS”。

## 1. 必读文件与现有代码位置

先阅读实际仓库中的文件；若文件路径已变化，以内容/真实 import 路径为准并在报告中列出：

- `AGENTS.md`、`docs/schema-v2.4-freeze-record.md`、`docs/data-contracts.md`、`docs/artifact-policy.md`、`docs/id-policy.md`
- `ARCHITECTURE_TASK_1_MASTER_PLAN.md`、`TASK_1_5_CODEX_PROMPT.md`、`docs/task-1.5-semantic-structure.md`
- `TASK_1_5_INDEPENDENT_REVIEW.md`、`CODEX_TASK_1_5_FREEZE_BEFORE_1_6_REPAIR_PROMPT.md`、`test_task15_independent_gaps.py`（若尚未加入项目，请从修复包取得）
- `src/engineering_rag/contracts/documents.py`、`contracts/protocols.py`、`contracts/artifacts.py`、`contracts/evaluation.py`
- `src/engineering_rag/modules/document_parser/api.py`
- `src/engineering_rag/modules/document_parser/internal/parser.py`、`config.py`、`pdf_backend.py`
- `src/engineering_rag/modules/document_parser/internal/mineru/{runner,adapter,normalizer,v24_adapter}.py`
- `src/engineering_rag/modules/document_parser/internal/{tables,formulas,semantic}/`（含侧车来源和待关联关系）
- `scripts/run_mineru_cases.py`、`scripts/assemble_mineru_tables.py`、`scripts/assemble_mineru_formulas.py`、`scripts/assemble_mineru_clauses.py`
- `tests/integration/test_task1_3_real_tables.py`、`test_task1_4_real_formulas.py`、`test_task1_5_real_semantics.py`
- 本包 `TASK_1_6_PIPELINE_DESIGN.md`、`TASK_1_6_EVALUATION_PLAN.md`、`TASK_1_6_TEST_MATRIX.json`、`TASK_1_6_ACCEPTANCE_CHECKLIST.md`

### 当前已知源码事实，先复核再操作

- `DocumentParser.parse(ParseRequest) -> Document` 是冻结的公共入口；`create_document_parser()` 支持 `document_engine="mineru"` 内部路径。
- 当前 `ParserSettings.max_selected_pages=20`，默认 `document_engine="baseline"`；本阶段代表集有 21 个不同物理页，不能一次调用突破保护上限。
- 之前 Task 1.5 原始交付独立验收结果为 **261 passed, 16 skipped**；需要手动启用真实产物测试才额外看到 5 个 PASS；**这些是旧版源码的历史基线，不是新提交的自动验收结论**。
- 上轮额外反例证明四项待核验缺陷：说明页 301 无分区证据时误判正文；unknown 页正文未进入 pending；不同 PDF 批次合并来源身份未拒绝；子 Block bbox 可越出原 Block。
- V2.4 允许规范正文与条文说明独立 Clause；强条 `is_mandatory` 缺证据保持 `null`；未核验 OCR/公式/表格不标 `verified`。
- 先区分 `Document Schema` 版本、`parser_version`、`MinerU` 版本、模型版本、评测数据集版本和产物版本，不要混用。

## 2. Gate 0 — 修复核验 / 前置条件

1. 记录 git commit、工作区状态、Python/WSL、MinerU/模型版本、CPU/GPU、可用 RAM/磁盘、PDF 真实 SHA-256；不得修改或推送远程仓库。
2. 执行：`python -m pytest -q`，针对四项缺陷运行 `tests/audit/test_task15_independent_gaps.py`（项目有此路径则用实际路径）。查看真实回放环境变量是否可用。
3. 若四项仍有未修复，先按既有 Task 1.5 修复书完成最小改动；不得简单把所有页面标 `unknown`、删除 pending 测试或绕开文件身份校验。
4. 如果真实原始 MinerU 产物/GB 50010 PDF 不存在，报告确切缺口。可以先开发离线管线和样例测试，但 **Gate 1 标记 BLOCKED**。
5. 确认冻结契约源码没有被修改；若本阶段需要新增公共字段，停止并提 ADR，不要偷偷扩展 `Document`。

## 3. Gate 1 — Parser 统一端到端调用

目标是让一个可复现入口（建议 `scripts/run_document_parser_e2e.py`）真正完成：

```text
FileStore.read + 原 PDF 物理页 / 文件哈希
    -> PyMuPDF 读取/校验
    -> MinerU 本地推理（或显式标记的 replay 模式）
    -> MinerU 原始产物 + 内部规范化结果
    -> 表格 + 公式语义组（含条件 / 式中解释去重）
    -> 页面区段判定 + 章节树 + 正文 / 说明 Clause
    -> 多批次可信合并与 pending/sidecars
    -> 严格 Document V2.4 验证 / JSON 往返
    -> 版本化 Artifact / Overlay / Report
```

- **真实模式**必须调用本地 MinerU；**回放模式**只能明确读取已保存真实 MinerU 产物；**synthetic 模式**仅用于独立单元测试，三种模式产物不得混淆。
- 默认先运行真实 PDF 第 16 页，再运行 49–50、126–127、28–29、37–38、24、301 等重点组，随后扩展到本包代表页集合。不要为使结果匹配样本硬编码 PDF 页内容或条文号。
- 同一条通用解析链路要支持普通正文、条文说明、公式条件、共享符号解释、无编号公式、表格碎片、跨页续表、未分类页面 pending。
- 本轮只对 **V2.4 已表达的真实信息**赋值；无法可靠归属，保留 `unknown` / `pending` / `partial` / `unverified` 和来源证据。
- 注意物理 PDF 页码从 1 开始，切页临时 PDF 的页序不能被误用作物理页；PDF bbox 统一 `pdf_points/top_left`。
- 不重复创建公式适用条件和“式中”解释 Body。不能简单删除混合文本或截断解释；未消费来源保留、跨页 pending 和 source lineage。
- 通过独立适配器/内部管线实现，不需要把 MinerU 内部 MiddleJson 类型暴露到冻结的公共 Protocol。

**推荐新增但可根据仓库实际调整的内部能力**：`ParseRunOrchestrator`、`BatchPlanner`、`CheckpointStore`、`StrictSourceMerger`、`ParserRunManifest`、`QualityReporter`。不要机械制造空类；优先复用已经存在的代码。

## 4. Gate 2 — 分批解析、可信合并与可恢复执行

### 4.1 批次和负载

- `--pages` 支持 1-based 页面列表/范围，去重、有序、界限检查；先按任务语义组合再拆成 **每批最多 20 页**（当前实现默认保护），不能在跨页表中间错误截断语义后又当作完整结果。
- 页数大于 20 时由编排器多次调用符合 `ParseRequest` 既有 `config.options` 类型的请求；保留跨批次上下文供统一后处理，不允许盲目拼接独立 Clause 缓存。
- 不在第 1 个批次就把只出现一半的公式/表格/Clause 标为完整；在收齐批次后重跑需要全局视图的保守归并与验证。
- 最终文档物理页索引有序、唯一，`page_count` 记录原 PDF 总页数；没处理的页面不要伪装成空白或已完成。

### 4.2 强制同源合并

合并前必须拒绝 `source_file.file_id`、`sha256`、`size_bytes`（两边提供时）、`page_count`、`standard.standard_code/edition/revision`、`bbox_coordinate_system`、`schema_version` 矛盾；校验页面重复 / Block ID 冲突 / Table 片段引用 / 公式 ID 冲突。`document_id` 一致**并不充分**。

重复页如果是幂等重试，需校验原始文件、输入参数、模型/解析版本和结果哈希一致，才能使用已有快照；不一致必须 fail closed 或进入明确人工冲突处理，不可默认取后一份。

### 4.3 快照、恢复和失败

- 构建 Parser **私有** run manifest（不擅改公共 `ArtifactManifest`），每批记录输入文件哈希、原物理页、执行档位、模型/工具版本、开始结束时间、运行状态、产物 SHA-256、诊断路径、尝试次数。
- 状态最少覆盖 `planned/running/succeeded/failed/blocked/skipped`，区分解析失败页与尚未执行页；写入使用临时文件 + 校验 + 原子 rename；支持 `--resume` 和可显式触发的 `--retry-failed`。
- 中断后可从上次成功的完整批次继续；不跳过损坏文件、不误把 stale cache 当新版本、不丢失成功的原始 JSON / overlay / logs。
- 故障注入包括：MinerU 超时、子进程非零退出、缺模型、写盘失败、磁盘空间不足、重复批次、错误物理页映射、篡改的 manifest/hash、混入另一份 PDF。
- 仍应遵守原始 PDF 不上传外部服务的政策。模型下载如需联网，只从经用户批准的源获取模型；不得把用户 PDF 或原始 OCR 传到外部 API。

## 5. Gate 3 — Golden Dataset 与可靠评估

1. 将先前的 **18 组/21 个物理页**标为 `candidate_pending_human_review`；另设 49–50 连续条文和 16/282 正文-说明关联样本。**候选不是金标**；保存真实 MinerU 原始输出不等于标注正确。
2. 实现轻量标注模板导出（JSONL/JSON + page image / overlay / source ID + 物理页坐标），供维护者审阅。人工核验后记录 reviewer、reviewed_at、dataset_version、source_sha256、label provenance。
3. 仅对 `verified` 的样本计算质量指标；未审页面只统计处理覆盖、V2.4 合规率、错误数、pending 数、耗时，不提供貌似精确的 CER/F1。
4. 指标至少包括：
   - PageType macro-F1、各类 P/R/F1、unknown 混淆；
   - OCR CER（中文 + 运算符单独观察）与阅读顺序；
   - bbox IoU / 几何非法率 / 物理页定位一致性；
   - 表格 raw_grid rowspan/colspan、cells / header_path、一页和跨页 Table 的关联 P/R/F1、数据值与表注正确性；
   - 公式检测/编号正确率、LaTeX 人工等价或归一化匹配、条件关联准确率、符号解释覆盖率、重复消费/漏消费；
   - Section/Clause 编号与边界、跨页关联、正文-说明归属及来源引用完整性；
   - 资源：处理页数、成功/失败/未处理页数、总 wall time、每页耗时中位/P95、峰值内存（能测则记录测量来源）、磁盘占用。
5. 每个指标明确 `numerator`、`denominator`、样本选择策略、置信/不足标记。没有 gold 时该准确率指标记为 `not_evaluated` 或 `null`，**绝不能写成 0%、100% 或空数据计算平均**。
6. 评价应能区分：上游 MinerU 识别错误、表格归并错误、公式语义错误、条文语义后处理错误、来源/物理页映射错误、人工未标注；给可回放失败案例、原图 overlay 和诊断。
7. 先产出真实样本基线，不凭主观印象设置统一高精度阈值。可以为**完整性、无数据污染、ID 与 schema 校验**设置严格硬门禁；识别精度阈值由真实金标和维护者确认。
8. 公共 `contracts/evaluation.py` 如与本任务需要的丰富诊断不完全匹配，使用 Parser 私有 sidecar JSON，**不修改已冻结或其他公共契约**。

## 6. Gate 4 — 性能、资源与全本可选模式

- 基线必须完成：单页、跨页组、21 个代表页的分批计划及实际执行（资源许可时），重试/恢复演示和报告。
- **默认绝不解析 441 页**。只有用户显式要求后，才启用 `--full-document`（或等效确认选项），先计算页数、模型资源需求、可用磁盘/内存，给出耗时和空间预算并要求执行确认；不能绕开每批最大页数限制。
- 全本运行如不可承受，应如实说明 `NOT_RUN` / `BLOCKED`，但保留可恢复的分批计划。**不得声称 441 页全本已准确解析**。
- WSL/Windows CPU/GPU 情况可配置并记录；不要假设有 CUDA 或可联网；OOM 自动限批/串行，重试设上限，不能无界循环。
- 安全控制：限制文件大小、原 PDF 哈希、临时目录逃逸 / Zip Slip（含 MinerU ZIP 原始产物）、拒绝危险符号链接与损坏 JSON，不执行 PDF 内嵌内容；敏感输入留本地，产物清理和持久化策略明确。
- 对规范特有的失败案例优先修复：第 50 页 `≤` 被识别为 `\\ll` 时不得在没有可信证据下自动改写，修正要留来源记录；公式解释跨页截断不得标完整；第 127 页不能将条文 9.1.3 吞进续表；第 301 页没有说明区段证据不能强行标正文。

## 7. 测试要求（从少到多）

**先确认当前路径和依赖，然后运行实际有效的命令；记录 skipped 原因**：

```bash
python -m pytest tests/audit/test_task15_independent_gaps.py -q
python -m pytest src/engineering_rag/modules/document_parser/tests -q
python -m pytest -q
ENGINEERING_RAG_RUN_REAL_MINERU=1 python -m pytest tests/integration -q
ruff check .
ruff format --check .
```

实际测试必须包含：

1. `tests/integration/test_task1_6_end_to_end.py`：从本地 PDF + 实际 MinerU（显式启用）到 Document 校验和真实证据。
2. `tests/integration/test_task1_6_replay.py`：使用**原版真实产物**回放，不需要模型，但不能冒称为重新推理。
3. `tests/document_parser/test_task1_6_batch_resume.py`（可按现有目录调整）：分批排序、hash、不兼容源、重复页、timeout、失败注入、恢复和幂等。
4. `tests/document_parser/test_task1_6_quality_metrics.py`：有/无金标、分母为零、部分标注、不同标签冲突、错误分类、公式条件去重。
5. 真实案例：16，49–50，28–29，37–38，126–127，24，301，16+282、文件身份负例、截断公式说明负例。
6. V2.4 `Document.model_validate_json(...)`、JSON round-trip 和 Clause 派生文本 cache/digest，不允许静默 invalid。

测试结束应有按类别划分的 pass/skipped/failed 数据，不得以跳过全链路真实测试换取总数全绿。

## 8. 输出产物与文件格式

建议将每次运行保存在 `data/eval/task1_6_e2e/runs/<run_id>/`（不提交用户 PDF、完整原始数据、模型权重到 Git）：

```text
run_manifest.json                  # Parser 私有运行 Manifest，含阶段状态、版本、配置和源哈希
batches/batch-*/manifest.json      # 每批物理页、真实模型运行/回放标识、输入输出哈希
batches/batch-*/raw/              # MinerU 原始 middle_json/ZIP/MD/HTML/图片
batches/batch-*/normalized.json   # 统一内部解析结果
batches/batch-*/partial.json      # 单批 V2.4 Document
final/document.v2.4.partial.json # 合并后已校验的合法 Document，partial 据事实定
final/semantic_pending_links.json
final/source_lineage.json
final/table_sidecars.json
final/formula_sidecars.json
final/formula_dedup_coverage.json
qa/overlays/                      # 真实 PDF 页面叠加与来源 ID
qa/gold_candidates.jsonl          # 人审候选，非金标
qa/gold_verified.jsonl            # 仅通过人审的标签，可能为空
qa/metrics.json                   # 指标含分母、评估状态
qa/error_catalog.json            # 缺失/误识别/合并失败诊断
qa/coverage.json                  # 处理、失败、unknown、pending 和跨页覆盖
qa/resource_profile.json
qa/quality_report.md
```

保存前重建/重新校验 Pydantic 文档、验证引用图、再计算文件 hash；Artifact 发布必须遵循正式 `artifact-policy`，不得将内部 run_manifest 当作 public `ArtifactManifest` 直接提交。

最终至少新增/更新：
- `docs/task-1.6-end-to-end-report.md`（包含真实运行证据和结论）；
- `docs/task-1.6-quality-analysis.md`（质量和缺陷优先级）；
- `docs/task-1.6-operations.md`（本地启动/重试/恢复/输出位置/资源预算）；
- 真实的端到端脚本和批次/评估模块；相关单元、集成和回归测试。

## 9. 成功判定与禁止事项

建议任务状态：
- **PASS**：前置缺陷通过、代表页本地 MinerU 真实推理和回放通过、可信分批恢复/合并、合法 V2.4、已有人审金标并生成有分母的指标、pytest/Ruff 通过，核心错误/限制完整披露。识别精度达标与否另给人工审议结论。
- **PARTIAL**：代码质量/测试通过但缺少 MinerU 重推理、人工金标或资源受限，仅能证明技术基础；必须明确哪些门禁未过。
- **BLOCKED**：前置 P1、文件身份污染、坏引用不可修复、缺少 PDF/模型阻止关键实际运行。

**不得**：修改 Frozen V2.4、以合成/回放冒充真实推理、以候选标签冒充金标、自动上传 PDF、把处理覆盖率冒充准确率、默认跑 441 页、无证据自动纠正公式数学符号、删掉失败用例、未授权推送 Git、擅自开始 Chunking 或其他模块开发。

### 最终向维护者报告的格式

1. Gate 0–4 状态和证据路径。
2. 代码/脚本/文档修改清单，冻结契约 diff（预期为 0）。
3. 环境信息、原 PDF SHA-256、总页数、实际 MinerU 模型版本、执行命令。
4. 实际推理页/回放页/未运行页，测试 pass/fail/skip 与 Ruff。
5. 容错/恢复演示，来源同一性与 JSON V2.4 校验报告。
6. 指标结果（标注版本、分子/分母；缺金标则 `not_evaluated`）、错误案例、资源开销。
7. 遗留问题和风险，建议的 `PASS/PARTIAL/BLOCKED`，以及是否建议进入下一模块。

完成 Task 1.6 后停止并等待维护者验收。
