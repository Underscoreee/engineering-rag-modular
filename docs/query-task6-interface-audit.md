# Task 6.0：Query 接口审查报告

审查日期：2026-10-18。代码基线：`ce9335e`；开始时 `git status --short` 为空。
本阶段仅交付设计文档。下文区分“当前实现”“已有声明”和“建议方案”，不启动 Task 6.1。

> Task 6.0.1 更新（2026-10-18）：第 1～7 节保留为 **Task 6.0 历史审查快照**，
> 其中“无 LLM/目录 Protocol”“计划 1.0”等描述不再是当前状态。当前契约与缺口处理结果见
> 第 8 节及 [ADR-Q-001](adr-task6-query-prerequisites.md)。历史测试计数属于 6.0，不是 6.0.1。

## 1. 仓库事实与证据

| 编号 | 实际文件 | 审查结论 |
| --- | --- | --- |
| E1 | [queries.py](../src/engineering_rag/contracts/queries.py) | Query DTO 已定义；不存在业务实现 |
| E2 | [retrieval.py](../src/engineering_rag/contracts/retrieval.py) | 两路请求、Hybrid 请求、过滤与统一结果已定义 |
| E3 | [protocols.py](../src/engineering_rag/contracts/protocols.py) | Query/Hybrid/LLM 相关边界见下表；没有 LLM Client Protocol |
| E4 | [Query API](../src/engineering_rag/modules/query/api.py)、[接口](../src/engineering_rag/modules/query/INTERFACE.md) | 只有重导出和未来接口说明；internal 只有空初始化文件，测试只验证 Protocol |
| E5 | [Hybrid service](../src/engineering_rag/modules/hybrid_retrieval/internal/service.py)、[fusion](../src/engineering_rag/modules/hybrid_retrieval/internal/fusion.py)、[merger](../src/engineering_rag/modules/hybrid_retrieval/internal/candidate_merger.py) | Task 5 已实现顺序双路检索、身份校验和融合 |
| E6 | [Keyword API](../src/engineering_rag/modules/keyword_retrieval/api.py)、[接口](../src/engineering_rag/modules/keyword_retrieval/INTERFACE.md)、[searcher](../src/engineering_rag/modules/keyword_retrieval/internal/searcher.py) | 已实现 BM25 与现有全部过滤字段 |
| E7 | [Vector API](../src/engineering_rag/modules/vector_retrieval/api.py)、[接口](../src/engineering_rag/modules/vector_retrieval/INTERFACE.md)、[searcher](../src/engineering_rag/modules/vector_retrieval/internal/searcher.py)、[embeddings](../src/engineering_rag/modules/vector_retrieval/internal/embeddings.py) | 已实现 COSINE；query_instruction 在 Vector 内拼接，不是 HyDE |
| E8 | [基础目录](../src/engineering_rag/infrastructure/)、[answers.py](../src/engineering_rag/contracts/answers.py)、[tasks.py](../src/engineering_rag/contracts/tasks.py)、[evaluation.py](../src/engineering_rag/contracts/evaluation.py) | 配置、观测、编排、通用评估以声明为主；无统一 LLM 实现或标准目录 |
| E9 | [冻结记录](schema-v2.4-freeze-record.md)、[ADR](architecture-decisions.md)、[数据契约](data-contracts.md)、[依赖规则](dependency-rules.md) | Document V2.4 Frozen；本次不修改任何公共 Schema/Protocol |

当前 Query 没有实际调用链；已存在的可调用链从 Hybrid 开始：
`DefaultHybridRetrievalService.search → Keyword.search → Vector.search → merge → fusion`。
Query 的 `plan/execute` 目前只是 Protocol 方法。README 已说明 Task 3～5 实现；
`docs/architecture.md` 仍称向量索引为后续任务，这是过时描述，本次记录、不修改无关文档。
冻结 tag `document-schema-v2.4` 解析到提交 `ebd9b29b3bb475401c8e91a30303ae46a8c119aa`。

## 2. 真实接口映射表

路径中的 `contracts/` 均指 `src/engineering_rag/contracts/`。调用关系中的 Query 调用属于设计，尚未实现。

| 类型/能力 | 实际定义位置 | 实际字段或签名 | 调用方 → 被调用方 | 状态 |
| --- | --- | --- | --- | --- |
| QueryRequest | `contracts/queries.py` | `question` 必填；`history=[]`、`filters=SearchFilters()`、`options=QueryOptions()`、`trace=None` | 上层 → Query | 已有模型 |
| ConversationTurn | 同上 | `role=user/assistant`、`content` | 上层 → Query/Generation | 已有模型；无 system/tool 角色 |
| QueryOptions | 同上 | `mode=hybrid`（keyword/vector/hybrid）、`top_k=10 > 0` | 上层 → Query | 已有模型 |
| QueryIntent | 同上 | `fact_lookup/requirement/comparison/explanation/unknown` | Query → RetrievalPlan | 已有枚举；不含本任务两类意图 |
| RetrievalPlan | 同上 | `schema_version=1.0`、`original_question`、`rewritten_queries=[]`、`hypothetical_document=None`、`intent=unknown`、必填 `retrieval_mode`、`hybrid_request=None` | Query.plan → 调用方；Query.execute 内部使用 | hybrid 模式必须有 hybrid_request，其他模式禁止它 |
| QueryResult | 同上 | `schema_version=1.0`、必填 `plan`、`evidence: list[RetrievalResult]=[]` | Query.execute → 上层 | 已能同时返回计划和真实证据 |
| QueryService | `contracts/protocols.py` | `plan(QueryRequest) -> RetrievalPlan`；`execute(QueryRequest) -> QueryResult` | 上层 → Query | Protocol；没有具体 Query 服务/工厂 |
| QueryConfig | 全仓搜索 | 无定义 | 组合根 → Query | 当前仓库未发现 |
| RetrievalRequest | 全仓搜索 | 无定义 | — | 当前仓库未发现；无需为命名一致性新增 |
| KeywordSearchRequest | `contracts/retrieval.py` | 必填 `query/index_name`；`top_k=10`、`filters`、`field_weights={}` | Hybrid → Keyword | 模型与实现均有 |
| VectorSearchRequest | 同上 | 必填 `query/index_name`；`top_k=10`、`filters`、`embedding_model_id=None` | Hybrid → Vector | 模型与实现均有 |
| HybridSearchRequest | 同上 | 必填 `keyword/vector/fusion_strategy`；`keyword_weight=0.5/vector_weight=0.5`、`candidate_k=50`、`top_k=10` | Query → Hybrid | 模型与实现均有；策略没有字段默认值 |
| SearchFilters | 同上 | `document_ids/standard_codes/editions/clause_numbers/content_types=[]`；`is_explanation/is_mandatory=None` | 上层/Query → 两路检索 | 只有这七项过滤字段 |
| RetrievalResult | 同上 | `schema_version`、`chunk_id/logical_chunk_id/document_id/content/standard`、可空 `clause_id/clause_number`、`page_start/page_end`、`score/rank/retrieval_source/score_type/index_name` | 两路 → Hybrid → Query | 无 source_refs、bbox、section、强条/说明状态返回字段 |
| HybridRetrievalService | `contracts/protocols.py` | `search(HybridSearchRequest) -> list[RetrievalResult]` | Query → Hybrid | Protocol + DefaultHybridRetrievalService 实现 |
| LLM Client Protocol | 全仓搜索 | 无结构化生成方法 | Query → 模型适配器 | 当前仓库未发现；GenerationService 不是通用 LLM 客户端 |
| GenerationConfig / ModelMetadata | `contracts/answers.py` | `config_id/max_output_tokens/temperature`；`provider/model_id/model_version` | 上层 → Generation；Generation → 上层 | DTO，未提供模型调用能力、连接、重试或 JSON 输出协议 |
| Observability | `contracts/protocols.py` | `log/record_metric/measure`，带 TraceContext | 各能力 → 观测适配器 | 只有声明与公开重导出 |
| ConfigProvider | 同上 | `get(key) -> str | None` | 组合根 → 配置来源 | 无通用具体加载器；各检索模块有自身配置 |
| Orchestrator | 同上 | `run_question(QuestionRequest) -> AnswerResult` 等 | 上层 → 跨阶段组合 | 声明；QuestionRequest.query 已引用 QueryRequest |
| EvaluationService | 同上、`contracts/evaluation.py` | `evaluate(EvaluationRequest) -> EvaluationReport` | 评估入口 → evaluator | 通用声明；未发现 Recall/MRR/nDCG 的通用实现 |

`QueryRequest` 本身无 schema_version；持久化计划/结果有默认 `1.0`，但字段不是 Literal 版本锁。
公共模型使用 `extra='forbid'` 与赋值校验；`NonEmptyStr` 仅检查长度，不拒绝纯空白、不做语义验证。
重跑边界 Pydantic 校验仍不等于候选标准真实存在，也不等于 LLM 改写保真。

## 3. Hybrid 的实际限制

两路文本可不同，`keyword.query/vector.query` 无须新增字段。两路 filters 也可不同；建议 Query
首版将同一已验证用户范围复制到两路，防止一支越出范围。Hybrid 不负责替 Query 验证范围。

`candidate_k` 是每路共享数量，Hybrid 会覆盖两路子请求的 `top_k`；子请求设置不同数量不能
实现非对称召回。最终 `top_k <= candidate_k`。两后端默认各限制 top_k ≤ 100；向量配置还有
HNSW `search_ef=64`。Query 配置需由组合根给出实测可用的候选上限，不能只看 DTO 的正整数约束。

策略真实值为 `rrf/weighted_normalized`，不是 `weighted_sum`。RRF 公共权重只能 0.5/0.5，
内部平滑参数默认 60；加权策略权重非负、和为 1，运行时还验证有限值。两种输出分别标记
`score_type=rrf/min_max_weighted_sum`；来源 `hybrid`，同分按 chunk_id 升序，最终 rank 从 1 开始。
Query 应保留这些值，不重新混分、换序或把 score 当概率。Hybrid 的 index_name 是两索引描述串。

## 4. 过滤可信度审查

没有发现可查询的权威标准目录、名称别名注册表、版次消歧服务或标准元数据 Protocol。
Document.standard、Chunk.standard、示例 JSON 是数据载体，不是完整或实时的在库目录。
Parser/Chunking Golden 数据也不是标准目录或检索相关性金标。

| 实际过滤字段 | 当前可做的本地校验 | 存在性/可信度限制 |
| --- | --- | --- |
| document_ids | 字符串非空白、来自显式可信作用域；不能由标准代码代替 | 无目录无法核验已入库及当前索引可见性；不得让 LLM 编造 ID |
| standard_codes | 格式候选、保留年份和原始字符范围 | 不能证明合法、已入库或与用户名称唯一对应 |
| editions | 非空白、保留用户版次语义 | 自由字符串，无统一命名和跨版本匹配服务 |
| clause_numbers | 工程编号格式候选 | 条文号仅在文档和正文/说明范围内有意义；无目录不能核验存在性 |
| content_types | ChunkContentType 枚举 | 合法值为 clause/paragraph/text/table/figure/formula/mixed，不是 PageType |
| is_explanation | 三态类型与用户明确意图 | 可以表达过滤意图，不证明已命中正确说明关系 |
| is_mandatory | 三态类型与用户明确意图 | 不能根据“应/必须”或 LLM 结论为规范条文赋予强制性 |

`None` 表示不施加该布尔条件，不能表示“仅返回状态未知”。同字段多值 OR，不同字段 AND。
标准名称、revision、section、页范围不属于 SearchFilters。名称可在未来目录中映射为
document_ids；修订版优先经目录映射到具体文档身份，不能把 revision 塞进 editions 冒充同义。
当前运行测试只能用人工提供的可信目录快照验证映射；没有快照时，以上字符串只有格式能力，
没有真实存在性校验能力。Query 不能绕过 Hybrid 去数据库临时发现标准。

## 5. 缺口分类与处理建议

每项均列出问题、证据、影响、最小方案、兼容性、测试和处理阶段。C 类只提出建议，本次不实施。

| ID/类别 | 问题与代码依据 | 影响及为何不足 | 最小建议与兼容性 | 所需测试 / 阶段 |
| --- | --- | --- | --- | --- |
| A1 无缺口 | E1/E2/E3：plan 内嵌 hybrid_request，Hybrid.search 已有 | Query 到检索、到 QueryResult 的主通路可直接表达 | 复用现有对象，毋须 RetrievalRequest 新包装；兼容 | DTO 往返、注入替身验证实际计划与调用相同 / 6.4 |
| A2 无缺口 | E2/E5：两路嵌套 query/filters 独立保留 | 足以区分关键词与 HyDE 语义文本 | 直接构造两路请求；不改 Hybrid；兼容 | 不同文本、相同范围、不修改输入 / 6.3～6.4 |
| B1 内部解决 | E1 无 QueryConfig；E2 要求显式索引/策略 | QueryRequest 不能提供所有部署参数，但这不是请求必需字段 | 后续内部不可变配置注入索引、candidate_k、策略、模型预算；兼容 | 参数范围、两路上限、未知配置拒绝 / 6.1、6.4 |
| B2 内部解决 | E1 rewritten_queries 无阶段标签 | 可保存查询列表，不能完整解释 rewrite/expansion 的来源和使用范围 | 内部严格阶段类型 + sidecar 保存 provenance，公共列表采用明确顺序；不滥用字段；兼容 | 去重顺序、HyDE 不入 BM25、文本预算 / 6.2～6.3 |
| B3 内部解决 | E1/E8 无 Query 专用失败实现 | 需要区分不匹配、模型失败、正常空命中 | 内部类型化异常、有限回退与 Observability 注入；当前返回类型无需变化；兼容 | 错误不吞没、阶段状态、原问题回退 / 6.1～6.4 |
| C1 公共缺口 | E1 QueryIntent 无 acquisition/exploratory | 无法在公共 plan.intent 诚实表达新分类；旧五类不与新两类一一对应 | 建议版本化新增 processing_intent 两类字段，保留旧 intent 并标记旧分类；精确字段/必填性需独立批准。增加字段对旧 extra=forbid 读取方也有风险 | 新旧 JSON、旧消费者、枚举、迁移和默认语义 / 6.1 前置 ADR |
| C2 公共缺口 | E1 mode 允许 keyword/vector，非 hybrid plan 无单路请求；E4 仅设计 Hybrid 注入 | 首版仅 Hybrid 无法兑现全部已有 mode，且不能把单路结果冒充 Hybrid | 首版显式拒绝非 hybrid，记录为能力限制，保留 Schema；若必须支持则另行批准单路计划/执行接口设计，不能改成权重 0 规避 | 三种 mode 明确接受/拒绝、无隐式改写模式 / 6.4 前置决策 |
| C3 公共扩展待定 | E1 QueryResult 只有 plan/evidence，无 warning、clarification 或 trace 回传 | 异常能中止，但不能成功返回结构化“请澄清/增强部分失败”状态 | 首版异常+私有诊断；若产品必须成功返回这些状态，另行版本化扩展 QueryResult；旧消费者风险需评审 | 严格旧版拒绝额外字段、空命中与澄清分离 / 6.1 前决定是否必需 |
| C4 非首版必需 | E2/E5 只有一个 candidate_k；无结果 source_refs | 两路不同召回数、精确 bbox 引用、分路分数诊断不能在当前结果中公开 | 首版共同候选数与页级引用足够；未来独立检索契约 ADR，影响 Keyword/Vector/Hybrid/Query/Generation；不是 Query 私加字段 | 来源字段往返、跨版本、双路结果一致性 / 后续独立任务 |
| D1 基础依赖 | E3/E8 无 LLM Client、JSON 生成接口、重试/用量记录 | GenerationService 面向答案和证据，不能代替 Query 的结构化推理接口 | 建议独立批准共享 vendor-neutral LLM Protocol/DTO，适配器由组合根注入；若只限 Query，可先私有能力边界。未创建任何新类型 | fake client、Schema 拒绝非法输出、超时/重试/用量、导入无副作用 / 6.1 前置 |
| D2 基础依赖 | E8 无标准目录能力 | 无法可靠把模型抽取条件变为精确范围 | 先注入人工可信且带版本的目录快照；共享目录服务需独立设计；不改 SearchFilters | 同名多版、未收录、空范围、显式条件冲突、目录与双索引快照 / 6.1 |
| D3 基础依赖 | E8 观测/配置/编排只有 Protocol | 声明不能自动产生日志、模型版本追踪或工作流 | 测试注入收集器，组合根以后提供适配器；不在 Query 导入基础设施实现；兼容 | trace/task 关联、敏感文本不默认落日志 / 6.1～6.4 |
| D4 基础依赖 | E8 只有评估描述类型，现有 Golden 属 Parser/Chunking | 无真实 Query 意图、过滤、相关性金标或通用排序指标实现 | 6.5 建立人工复核数据与小型可复现评估器，不能虚构分数；不必现在扩 Evaluation Schema | 无效标签排除、来源/版本校验、指标手算、零命中 / 6.5 |

## 6. 审查结论

已具备 Query → Hybrid → RetrievalResult → QueryResult 的 DTO 和 Protocol 骨架，缺少 Query
业务实现及 LLM/目录支撑。两路不同查询文本是已支持能力，不构成契约缺口。意图枚举冲突是
Task 6.1 前的明确契约门槛；完整 Query 功能不能仅靠现有接口宣称已经可用。

建议先批准 C1 与 LLM 边界，再启动 Task 6.1；首版使用 hybrid 模式，其他模式显式不支持，
未匹配的显式标准范围中止并请求澄清。其余设计见
[数据流设计](query-task6-dataflow-design.md)与[开发路线](query-task6-roadmap.md)。

## 7. 本阶段实际验证

在项目 `.venv` 内执行，日期 2026-10-18：

| 检查 | 实际结果 |
| --- | --- |
| `python -m pytest -q` | 433 passed，24 skipped，56.48 秒 |
| `python -m pytest tests/contracts tests/architecture -q` | 125 passed |
| 七个模块分别执行独立 pytest | Parser 165、Chunking 36、Keyword 30、Vector 9、Hybrid 34、Query 1、Generation 1，全部 passed |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 303 files already formatted |
| 文档 Python 示例 | 执行成功，两路 query 独立且 RetrievalPlan JSON 往返通过 |
| 文档链接、空白及 diff 范围 | 相对链接有效；`git diff --check` 通过；只有三份新设计文档 |

Query 与 Generation 的各 1 项测试只验证 Protocol 声明，不能视为业务功能通过。
本阶段没有启用真实数据库、MinerU、真实 Embedding 或 LLM 集成测试；完整 pytest 中的
24 项跳过不能计为真实集成通过。没有改动业务源码、公共契约、依赖或已有文档，没有 Git 提交。

## 8. Task 6.0.1 当前状态

| 原缺口 | 实际处理结果 | 仍需后续工作 |
| --- | --- | --- |
| C1 双意图 | 保留 QueryIntent；新增 ProcessingIntent，RetrievalPlan.processing_intent 必填；计划/结果 Literal 2.0；显式迁移要求传入意图 | 意图识别业务与人工评估未实现 |
| D1 LLM 边界 | contracts/llm.py DTO、StructuredLLMClient.generate Protocol、validate_output 纯校验与离线替身已提供 | 真实模型、SDK 适配器、数据传输政策未定 |
| D2 标准目录 | contracts/catalog.py DTO、StandardMetadataCatalog.lookup Protocol；四种结果、目录快照、测试标记、入库范围绑定已提供 | 无生产目录/匹配器；不支持条文存在性验证 |
| C2 单路模式 | 已采纳首版 Hybrid-only，保留 QueryOptions 三种值 | future service 明确拒绝 keyword/vector，执行逻辑未实现 |
| C3 成功结果状态 | 已采纳异常式失败，QueryResult 不新增状态字段 | 后续 Query 以最小异常体系区分失败；2.0 升版仅因嵌套计划变化 |
| D3/D4 观测/评估 | 未扩展 | 依然只有公共声明/已有领域工具，真实 Query Gold 未建设 |

QueryService 方法和 QueryRequest 未变；无 RetrievalRequest，Hybrid/Keyword/Vector/Document
契约未变。当前唯一新增公共依赖来自 contracts，不涉及跨模块内部导入或真实外部调用。
