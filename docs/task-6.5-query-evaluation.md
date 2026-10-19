# Task 6.5：Query 人工金标与端到端评估

日期：2026-10-18。代码基线 `b972608`，初始工作区干净。

当前结论：**评估基础设施与离线演示可验收；真实质量评估 NOT RUN，整体 PARTIAL。**
维护者已明确当前没有 Query 专用人工核验金标，授权生成示例继续；本次未生成任何真实
verified 标签，未使用 Parser 金标冒充 Query 金标。没有调整检索算法或业务逻辑。

## A. 数据集建设与人工流程

### 已交付数据

| 数据 | 路径 | 状态 |
| --- | --- | --- |
| 虚构可运行演示 | examples/query_evaluation/v1/ | 6 Chunk、8 draft 查询、9 draft qrels；0 条人工 review |
| 真实 GB 50010 待审查目录 | data/evaluation/query/gb50010-v1/ | 1305 Chunk 只读来源绑定；0 查询、0 qrels；需人工填写 |
| 实验产物 | data/eval/task6_5_query/runs/ | 与数据集分离，每个 run_id 独立且不可覆盖 |

示例 manifest.is_test_fixture=true，不能产生正式指标。所有示例查询与相关性均为格式/流程
演示，不是实际工程证据；review_log.jsonl 为 0 字节。真实目录 is_test_fixture=false 但仍是
空待标注数据集，formal_ready=false；is_test_fixture=false 不等于人工核验完成。
真实 data/ 目录沿用现有 Git 忽略规则，需另行归档；未强制添加或改写忽略规则。

真实语料为 `data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json`，
SHA-256 `49daa3d96006149b62b5887f72082d27a23e37ce15aeb50349807680d800f162`，
chunking_version=clause-first-1.0.0，文档 `doc-dab4ba42814d5a878df723d32b346337`。
覆盖：815 clause、374 formula、73 table、24 figure、19 paragraph；452 个条文说明。
只有 GB 50010-2010 / 2015年版，全部 1305 个 is_mandatory=null，因此跨标准正例与已核验
强制性正例均缺失，不能为了凑 50～100 条而编造。规范版本不等于 Chunk 或索引快照。

### 人工创建与复核

1. 固定只读 ChunkBatch、来源 Document/PDF 和知识库双索引快照；先核实规范版本与权限。
2. 使用 annotation_guidelines.md，从实际工程需求创建问题。query_id 稳定，初始 draft/pending。
3. caller_filters 是真实调用输入；expected_filters 是人工答案，不自动传入 Understanding。
   标注 processing_intent、预期 retrieve/reject；reject 必填既有错误码，不能当普通无命中。
4. 在 query 原文按 Python 字符 [start,end) 标注标准、编号、数量/单位、否定/条件保护项。
5. 人工查阅目标 Chunk 的实际 content、相邻条文、页码/Block 来源及规范版本，记录 qrels 0～3。
   0 不相关；1 弱相关不能独立支持；2 部分支持；3 核心证据。全部 >0 目标必须在同一过滤范围。
6. 检索池只提供候选，绝不能自动转 verified。多 Chunk 共同支持分别标注；正文与说明分别识别；
   公式条件/符号、完整跨页表格和表注需一起检查；强制性状态未知不能凭“必须”推断。
7. 人类复核者填写 review_log：review_id、query_id、可空 chunk_id、reviewer、真实时间、
   human_verified=true、decision、rationale；query/qrel 的 review_id 必须精确对应。
   只有完成该步骤才能手动改 verified；争议标 disputed 并保留记录。
8. 创建新 dataset_version，不覆盖旧版本；更新数量与四份文件原字节 SHA-256，重新只读校验。
   更换 Chunking/语料后必须重核目标，不能猜测或自动迁移旧 Chunk ID。

Review 记录是维护者信任声明，不是软件能鉴别的人类身份证明。自动脚本不会创建人工复核记录。
不确定的语义、相关性或跨标准关系留待审查，不用 HyDE/模型自评作事实。

## B. 实现、指标及实验入口

复用 `EvaluationService.evaluate(EvaluationRequest) -> EvaluationReport`，工厂位于
`engineering_rag.infrastructure.evaluation.api.create_evaluation_service`。
实际输入配置、必填项、DI 和快照约束见 [Evaluation 接口](../src/engineering_rag/infrastructure/evaluation/INTERFACE.md)。

ADR-E-001（本任务采纳）：不修改公共 Evaluation/Query Schema。数据集、实验配置和详细汇总
采用评估私有 1.0 格式；公共 EvaluationRequest.config 仍是标量字典；公共报告仅保存真实指标
与失败。模拟指标独立命名 offline_simulation，正式和未运行分数不能混淆。

排名定义：二元相关性 relevance>=2（可配置 1～3），Recall=命中相关数/全部相关数，
Precision=命中相关数/K（短结果仍除 K），MRR=首个相关名次倒数，HitRate=是否至少命中一次。
nDCG 使用全部分级 gain=2**grade-1 与 log2(rank+1) discount。未定义分母 null；不能把全部
预测错误的 F1 错算成 null（有有效标签时结果是 0）。未判定命中视为零 gain，但不假称 qrels
充分，数据池偏差需人工记录；重复命中 ID 拒绝。正式阈值变化时必须仍有对应有效相关目标。

阶段指标包含意图两类混淆矩阵/Accuracy/各类 P/R/F1/Macro-F1、七项过滤、范围违规、逐查询
保护项精确保留、增强接受数量与状态、耗时和已知用量。无法自动判定的无关性、事实编造率、
自由语义等价和成本为 null，并保留原因；它们不是本次已完成的人工质量结论。
缺失预测/失败样本保留分母与覆盖统计，不能只报成功样本均值。字面保留只是必要检查，不证明
词序、逻辑或语义未变。使用同一查询人口配对统计改善/退化/持平/无法比较，不宣称统计显著。

各变体共享人工范围、语料/索引、candidate_k、融合参数；实际预测范围不等时记录安全失败，
不通过覆盖错误 filters 使结果变好。Raw 用相同人工范围，预期 reject 查询在 Raw 显式 skipped；
其他变体使用实际 Query.execute 一次。Rewrite-only 关闭增强，两个单增强变体不允许把回退
冒充成功，Full 使用当前合法可选回退；Acquisition 全部按正常策略跳过增强。

### 可直接运行的虚构示例

以下在项目根目录、已激活 `.venv` 中运行；脚本也支持绝对路径与其他工作目录。
每次换一个 run_id，已有运行目录不得覆盖。

```bash
python scripts/evaluate_query_pipeline.py \
  --dataset examples/query_evaluation/v1 --dataset-version 1.0-draft \
  --corpus examples/query_evaluation/v1/corpus.chunk_batch.v1.json \
  --corpus-snapshot-id fictional-engineering-corpus-v1 \
  --mode validate_only --ks 1,3,5 \
  --output-dir data/eval/task6_5_query/runs --run-id demo-validate-v1

python scripts/evaluate_query_pipeline.py \
  --dataset examples/query_evaluation/v1 --dataset-version 1.0-draft \
  --corpus examples/query_evaluation/v1/corpus.chunk_batch.v1.json \
  --corpus-snapshot-id fictional-engineering-corpus-v1 \
  --mode offline_test --variants raw,rewrite,rewrite_expansion,rewrite_hyde,full \
  --ks 1,3,5 --candidate-k 50 \
  --keyword-index fixture_keyword --vector-collection fixture_vector \
  --output-dir data/eval/task6_5_query/runs --run-id demo-offline-v1
```

第一条验证文件/目标但标记 DRAFT_VALIDATED，不代表正式金标；第二条使用固定假响应、
固定语料顺序的检索替身和实际 Query/Hybrid 公开实现，只证明流程与计算。它不读取 qrels
制造预测，不是 BM25/Embedding 的替代算法。所有模拟指标都带非真实质量标记。

### 真实待标注语料的只读校验

```bash
python scripts/evaluate_query_pipeline.py \
  --dataset data/evaluation/query/gb50010-v1 --dataset-version 1.0-pending \
  --corpus data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json \
  --corpus-snapshot-id gb50010-full-v6-semantic-cleanup-49daa3d96006 \
  --mode validate_only --ks 5,10,20 \
  --output-dir data/eval/task6_5_query/runs --run-id gb50010-draft-validation-v1
```

加 `--require-verified` 会拒绝空/未复核数据。这是预期保护，不得删除该门禁。

### 正式运行的接口示例（当前不能完成真实评估）

标注完成后新增版本目录，提供经真实只读 inventory 核验的 IndexSnapshot 和可信运行工厂。
工厂由 `--runtime-factory package.module:function` 显式选择，签名为
`(EvaluationRequest) -> EvaluationRuntime`。函数仅由可信组合根提供；不要从金标/模型文本载入代码。
工厂必须使用传入的 Probe LLM / Guarded Hybrid，并从 Query 公开 API 配置变体开关和共享预算。

IndexSnapshot 绑定 corpus hash、Chunk inventory hash、document_ids、双索引不可变版本、模型
和编码策略，runtime.verify_snapshot 必须核查当前实际索引；不能复制文件即宣称在线核验。
当前公共检索 Protocol 不提供全量 inventory，需可信组合根的只读适配能力，缺少则 NOT RUN。
Query 无真实 LLM 适配器时不能为了运行改用 Fake。

```bash
# 接口示例：路径、索引、模型和工厂均须替换为已验证的部署配置。
python scripts/evaluate_query_pipeline.py \
  --dataset /path/to/reviewed-query-dataset --dataset-version REVIEWED_VERSION \
  --corpus /path/to/immutable-chunk-batch.json --corpus-snapshot-id CORPUS_SNAPSHOT \
  --mode retrieval_eval --variants raw --ks 5,10,20 \
  --keyword-index VERIFIED_ES_INDEX --vector-collection VERIFIED_COLLECTION \
  --embedding-model-id VERIFIED_EMBEDDING_MODEL \
  --snapshot-manifest /path/to/verified-index-snapshot.json \
  --runtime-factory approved_eval_runtime:build \
  --require-verified --output-dir /path/to/experiments --run-id real-raw-v1
```

真实 LLM 全变体将 mode 改 llm_e2e_eval、variants 改为五种；必须已有真实模型/目录配置及
批准的数据政策。retrieval_eval 的非 Raw 变体明确 NOT RUN，不偷偷用替身生成改写。

## C. 产物、失败与可复现性

每次输出 config.json、metrics.json、per_query_results.jsonl、evaluation_report.json、report.md。
记录 manifest/corpus hash、四份标注文件 hash、版本、配置、快照证明、实际请求/结果、逐查询
错误类型/代码、耗时、模型尝试、Prompt 版本、策略指纹和已知用量。结果匹配真实源 Chunk，
不存在/内容变更/页码不符不能计分。输入文件只读，实验目录不可覆盖、不可通过符号链接写金标。

标准日志只收集 trace 匹配的安全元数据；从任务输出原始候选不能推断已通过业务校验。
阶段状态来自既有校验后日志；无法观测为 not_observed。模型调用耗时不是完整业务阶段耗时，
两者分别存储。缺用量为 null；无真实计费信息成本为 null，不能编造价格或节省比例。
产物含问题/已接受文本与实际证据，需访问控制；默认普通日志不记录全文。

CLI 成功/只校验返回 0；输入错误、NOT RUN 或 PARTIAL 返回非零。DRAFT_VALIDATED 只表示
草稿结构可读，不得用于正式评估。source Document/PDF 哈希有声明/独立核验区别：真实审计
已重算 Document hash，但 PDF hash 仅来自 Document 的记录，未重新推理或替换原文件。

## D. 实际验证与真实评估状态

修改前基线：838 passed、24 skipped，9.69 秒，无 Parser 收集阻塞。
最终测试命令和实际计数将在本报告验收记录中追加，绝不使用旧任务计数冒充本次结果。

- 金标/目标校验器及演示：已实际执行；演示与真实空队列均不是正式金标。
- Fake 依赖的指标、阶段与五变体流程：已实现并实际运行，不是相关性质量结论。
- 真实 Hybrid 检索评估：NOT RUN，缺人工 qrels、真实索引快照及配置的验证适配器。
- 真实 LLM 端到端评估：NOT RUN，另外缺已配置的真实模型/生产目录与批准数据政策。

本次不启动 ES/Milvus、不改索引，不下载模型，不调用真实 LLM，不报告实际 Recall/MRR/nDCG。

## E. 评估结论与待决事项

目前不能回答增强是否提高真实检索质量，不能预设 HyDE/Expansion 必然有效。交付的是安全、
可重复的评估能力与人工标注入口；没有人工依据的事实/语义指标保留 null。
需要先补充 50～100 条有真实工程依据的人工问题及完整分级候选池，复核并固定模型与索引。
现有单 ChunkBatch 格式只能代表一个文档；跨标准实际比较暂为覆盖/格式缺口，不虚构多规范。
人工语义/事实审核字段尚无逐变体标签集，相关率 NOT MEASURED；不要用模型自评分数替代。

所有改动限定在 Evaluation、评估测试/脚本、示例和接口文档；公共契约与其他业务逻辑保持原样。
不自动提交 Git，不启动 Task 7 或 Generation；等待维护者审查。

## F. 最终验收记录

所有命令在项目 `.venv` 内实际执行。没有 Parser 测试路径收集错误，也没有为通过回归修改
已有业务断言。新增反例确实复现了弱相关范围、保护项重复、拒绝范围违规汇总及 Raw 口径问题，
随后定向修复；模拟失败、范围冲突、未知来源、版本/哈希冲突与覆盖防护均有测试。

| 实际命令 | 结果 |
| --- | --- |
| `python -m pytest tests/evaluation -q` | 145 passed，5.10 秒 |
| `python -m pytest src/engineering_rag/modules/query/tests -q` | 342 passed，4.24 秒 |
| `python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q` | 34 passed，0.25 秒 |
| `python -m pytest tests/contracts -q` | 175 passed，0.66 秒 |
| `python -m pytest tests/architecture -q` | 13 passed，1.23 秒 |
| `python -m pytest -q -rs` | **987 passed、24 skipped、0 failed，14.72 秒** |
| 其余五模块分别独立 pytest | Parser 170、Chunking 36、Keyword 30、Vector 9、Generation 1 passed |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 366 files already formatted |
| `git diff --check` | 通过 |

Generation 的 1 项仍仅验证 Protocol。24 项跳过与基线相同：原 PDF audit 1、真实 ES 1、
MinerU 保存产物/回放 19、真实 Chunking 1、真实 Embedding 1、真实 Milvus 1；未启用它们，
不能把跳过项算作真实集成通过。本任务所有新增评估测试均离线且未跳过。

完整 pytest/Ruff/diff 日志位于
`data/eval/task6_5_query/verification-lS4VhN/`（早期日志及实验均保留，不覆盖）。

最终交付实验：

- `runs/demo-offline-v3/`：当前实现指纹，40 条逐查询变体记录；35 success、4 expected_rejection、
  1 Raw skipped，5 个变体均完成。official_quality_metrics=null，公共 report.metrics 为空；
  仅 offline_simulation 有测试用计算结果，不是实际检索质量。
- `runs/gb50010-draft-validation-v2/`：真实 1305 Chunk 来源/版本/hash 校验通过，空标注队列
  DRAFT_VALIDATED、formal_ready=false，不是人工金标完成。
- `runs/gb50010-retrieval-not-run-v1/`：真实检索评估 NOT RUN，正式分数 null。
- `runs/gb50010-llm-not-run-v2/`：真实模型端到端评估 NOT RUN，正式分数 null。

以上 runs 均相对 `data/eval/task6_5_query/`。config.json 记录 Python/Pydantic 版本与
Evaluation 实现源码指纹；最新离线指纹为
`7cc5d02582a2023c1e45d9e04393ec5ca3b94be06c14882d91f4ceb4b7345090`。
原真实 ChunkBatch SHA-256 在最终检查再次核对，未变化。没有启动任何外部模型或数据库。
Raw 的意图/过滤预测评分明确 not_applicable，不把人工 oracle 范围算作模型完美预测；
其检索与后端范围安全性仍正常评估。

### 修改文件清单

共 28 个版本控制范围内的新增/修改文件，另有受 data/ 忽略的待审查数据与实验产物。

| 范围 | 文件 |
| --- | --- |
| Evaluation 公开入口/文档 | `infrastructure/evaluation/api.py`、`INTERFACE.md` |
| Evaluation 私有实现 | `internal/__init__.py`、`dataset.py`、`metrics.py`、`summary.py`、`run_models.py`、`guards.py`、`telemetry.py`、`service.py`、`offline.py` |
| 执行入口 | `scripts/evaluate_query_pipeline.py` |
| 独立评估测试 | `tests/evaluation/__init__.py`、`test_dataset.py`、`test_metrics.py`、`test_summary.py`、`test_pipeline.py`、`test_cli.py` |
| 架构门禁 | `tests/architecture/test_evaluation_boundaries.py` |
| 文档 | 本报告、`modules/query/INTERFACE.md` |
| 示例 | `examples/query_evaluation/v1/` 下 README、准则、corpus、manifest、queries、qrels、review_log 共 7 文件 |

表中 infrastructure/modules 路径前缀为 `src/engineering_rag/`。
公共 contracts、依赖 pyproject.toml、Query 生产源码及其既有测试、Parser/Chunking/Keyword/
Vector/Hybrid/Generation 均无 diff。没有自动 Git 提交。

最终结论：**基础设施与离线流程 PASS；人工数据建设未完成，真实质量评估 NOT RUN；
整体 PARTIAL，等待维护者补充人工核验与真实运行依赖后审查。**
