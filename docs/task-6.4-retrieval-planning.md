# Task 6.4：Retrieval Planning 与 Hybrid 集成验收报告

日期：2026-10-18。基线提交：`255e07a`（Task 6.3），开始时工作区干净。
环境：项目 `.venv`，Python 3.11.17、Ruff 0.17.0。未新增依赖、未自动提交。

结论：**Task 6.4 离线功能及模块边界 PASS；真实模型、生产目录和数据库端到端质量尚未验证。**
本结论不表示真实检索质量达标，不启动 Task 6.5 或 Generation。

## 1. 实现与公共入口

`engineering_rag.modules.query.api.create_query_service` 返回 DefaultQueryService，结构上符合
既有 QueryService Protocol：plan(QueryRequest) → RetrievalPlan、execute(QueryRequest) → QueryResult。
没有修改 Query Schema 2.0、检索 1.0、Document Frozen V2.4 或任何公共 Protocol。

工厂复用 QueryUnderstanding、QueryRewrite、QueryEnhancement，并注入同一个公共
StructuredLLMClient、StandardMetadataCatalog 和 HybridRetrievalService。模型端点、凭据、
SDK 与检索后端的创建仍归组合根。本模块没有下载、连接、写索引或文件副作用。

## 2. 实际数据流

plan：复制校验请求 → 检查 hybrid-only/top_k → Understanding → Rewrite → Enhancement →
检查阶段对应关系和索引范围 → 构造两路请求及 RetrievalPlan。

execute：调用一次 plan → 复制 plan.hybrid_request → 调用一次 Hybrid.search →
校验实际检索结果 → 返回 QueryResult(plan, evidence)。

acquisition 的 enhance 入口返回 skipped_by_intent，两种增强都不调用模型。
exploratory 按已有开关和有界纠正预算执行，不增加任何上游重试或重复处理。
plan 不检索；execute 不另行理解、改写、生成增强或融合。外部先 plan 再 execute(request)
会规划两次，公共接口没有 execute(plan)，也没有隐含计划缓存。

输入、阶段传参、配置和返回结果独立复制，不共享逐请求可变状态。Query 不关闭注入资源。
检索结果不改分数、rank、列表顺序、内容、标准、页码或身份；只有本次 Hybrid 返回值可以是证据。
正常无命中与后端异常明确区分。注入 Hybrid 修改提交请求、返回非法模型或非有限分数时拒绝成功。

## 3. ADR-Q-004：有界单字符串规划

状态：Adopted，Task 6.4 明确授权。现有 VectorSearchRequest.query 只有单字符串，
HybridSearchRequest 只有一个 vector 子请求，因此不新增多查询契约，不修改融合算法。

- Keyword：主改写逐字保留，以换行追加已验证 Rewrite 同义词；稳定去重、去空，默认最多
  4 项/每项 64 字符，超预算整项不附加。不写 ES DSL，不使用增强作为同义词。
- Acquisition Vector：主改写。
- Exploratory Vector：completed 且符合规划字符预算的 HyDE；否则按原顺序选第一条有效且
  符合预算的 Expansion；否则主改写。不根据不存在的评分挑选，不拼接多个扩展。
- 主查询超任一路预算时明确失败，不能截断保护约束。默认两路各 8192 字符。
- plan.rewritten_queries 保留主改写及全部已验证扩展，稳定去重；不代表实际多次搜索。
  hypothetical_document 保留已验证 HyDE，实际采用哪条文本以嵌套 vector.query 和策略日志为准。
- HyDE 不进入 Keyword、filters、evidence、引用、Document 或 Chunk。过滤不从增强重新抽取。

确定性成立的前提是相同已验证阶段结果与相同配置；真实模型输出、请求 ID 和耗时不承诺一致。
本阶段不改变 6.2/6.3 的受控生成限制，也没有实现自由假设文档的安全证明。

字符预算不等于模型 Token 预算。向量模块仍添加 query_instruction，并由其实际模型编码；
Query 不导入其 tokenizer，不保证任意长增强不会被实际模型截断。正式部署需设置适合模型的
文本上限，另以真实模型验证长查询的约束保留情况。

## 4. 过滤与参数映射

唯一公共定义来源：`contracts/queries.py`、`contracts/retrieval.py`、`contracts/protocols.py`。

| 参数 | 实际来源及处理 |
| --- | --- |
| document_ids/standard_codes/editions/clause_numbers/content_types | Understanding 已验证结果，同字段 OR、跨字段 AND；两路各持有副本 |
| is_explanation/is_mandatory | 原三态语义，false 不丢失，null 不筛选；不推断规范法律效力 |
| options.mode | 仅 hybrid；keyword/vector 在模型调用前报 unsupported_mode，不改变 DTO |
| options.top_k | 原值映射到 Hybrid.top_k；默认 10，超过 candidate_k 报错，不静默调整 |
| candidate_k | PlanningConfig 默认 50，两路子请求 top_k 同为 50，Hybrid 按既有逻辑再覆盖为共享候选数 |
| 候选预算 | keyword_candidate_limit=100、vector_candidate_limit=64；candidate_k 不得超过任一预算 |
| 索引/Collection | PlanningConfig.scope，须与 Understanding 的可信目录索引对一致 |
| fusion_strategy | 配置默认 rrf；也支持既有 weighted_normalized |
| 权重 | 默认 0.5/0.5；RRF 只允许此值，加权策略有限非负且和为 1 |
| embedding_model_id | 可选可信配置原样传 Vector，默认 null；不由 LLM 路由模型 |
| field_weights/rrf_k | 不覆盖 Keyword 默认字段权重；RRF 平滑常数仍由注入 Hybrid 配置管理 |

候选上限是组合根的部署声明，不是数据库发现结果；默认兼容现有两后端 max_top_k=100 和
Vector search_ef=64。部署调参时必须同步确认实际后端，Query 不窥探其他模块私有配置。
QueryOptions 只有 mode/top_k，其他参数来自内部配置，不新增公共请求选项。

上游范围错误仍使用 UnderstandingError/RewriteError/EnhancementInputError，Hybrid 错误原样传播。
局部 QueryPlanningError 只补充 unsupported_mode、invalid_parameters、invalid_upstream、invalid_result；
配置/模型非法保留 Pydantic ValidationError。仅可选增强的合法失败结果允许回退。
空交集不能改成无约束空列表；未知、歧义、不可用目录不得退化为全库。

## 5. 文件清单

| 文件 | 变化 |
| --- | --- |
| `src/engineering_rag/modules/query/api.py` | 公开工厂、服务类与配置重导出，保留原有 canonical DTO/Protocol 和迁移导出 |
| `src/engineering_rag/modules/query/internal/planning_models.py` | 新增复用式配置、同模块注入 Protocol、最小规划错误 |
| `src/engineering_rag/modules/query/internal/planning.py` | 新增纯文本选择及既有公共请求/计划投射 |
| `src/engineering_rag/modules/query/internal/service.py` | 新增阶段编排、一次执行、结果重验和安全日志 |
| `src/engineering_rag/modules/query/tests/test_planning.py` | 新增阶段替身规划/执行、参数/失败/隔离/确定性测试 |
| `src/engineering_rag/modules/query/tests/test_pipeline_integration.py` | 新增实际三个 Query 阶段与实际 Hybrid 的离线组合测试 |
| `tests/architecture/test_query_dependency_contracts.py` | 原阶段禁检索门禁定向开放编排 service，其他阶段继续禁止，验证注入公共 Hybrid Protocol |
| `src/engineering_rag/modules/query/INTERFACE.md` | 同步真实入口、配置、映射、错误、生命周期与组合示例 |
| `docs/task-6.4-retrieval-planning.md` | 本报告及 ADR-Q-004 |

公共 contracts、pyproject.toml、Parser/Chunking/Keyword/Vector/Hybrid/Generation 均无 diff。
没有调整原有业务算法或原有断言来迎合新测试。

## 6. 实际测试结果

以下命令使用项目 `.venv/bin/python` / `.venv/bin/ruff`；表中 python/ruff 表示已激活此虚拟环境。

| 实际命令/检查 | 结果 |
| --- | --- |
| 修改前 `python -m pytest -q` | 781 passed、24 skipped，22.45 秒，无收集错误 |
| `python -m pytest src/engineering_rag/modules/query/tests/test_planning.py src/engineering_rag/modules/query/tests/test_pipeline_integration.py tests/architecture -q` | 66 passed，1.28 秒（其中新增 Query 测试 57） |
| `python -m pytest src/engineering_rag/modules/query/tests -q` | 342 passed，3.59 秒 |
| `python -m pytest tests/contracts -q` | 175 passed，0.62 秒 |
| `python -m pytest tests/architecture -q` | 9 passed，0.57 秒 |
| `python -m pytest -q -rs` | 838 passed、24 skipped、0 failed，10.91 秒 |
| 其他六个业务模块分别 `python -m pytest src/engineering_rag/modules/<module>/tests -q` | Parser 170、Chunking 36、Keyword 30、Vector 9、Hybrid 34、Generation 1 passed |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 346 files already formatted |
| `git diff --check` | 通过 |
| INTERFACE.md 公开组合示例 | 注入离线模型/目录/Hybrid 后执行成功，4 次模型阶段调用、1 次检索，JSON 往返及相对链接通过 |

Generation 的 1 项仅验证 Protocol，不代表 Generation 已实现。全量跳过项与基线相同：
原 PDF audit 1、真实 Elasticsearch 1、已存 MinerU 真实产物/回放 19、真实 Chunking 1、
真实 Embedding 1、真实 Milvus 1；相应显式启用变量未配置，没有把这些测试计为通过。

新增 57 项包含配置与非法参数的参数化反例；涵盖两类意图、两种融合策略、文本优先级、
单路/双路增强失败、正文保护、同义词来源、全部过滤字段、目录失败、一次调用、JSON 往返、
真实 Hybrid 离线组合、结果保真与非有限数拒绝、输入/配置隔离、日志及确定性。
开发中新增反例确实暴露非有限分数错误分类、测试夹具共享引用及新架构测试注解假设问题，
已分别修复新实现/夹具/注解校验并重跑通过；没有修改上游业务逻辑。

真实 Query LLM、真实 ES/Milvus 和 Embedding 本次均未调用。使用实际 Hybrid 算法 +
离线 Keyword/Vector 替身的测试仅证明组合接口、排序与参数传递，不是数据库集成或相关性评估。

## 7. 风险与可观测性

复用标准 logging：每阶段状态/耗时，规划两类意图、增强状态、选择策略、候选/最终数量，
执行结果数量；既有模型阶段记录模型/Prompt/策略版本、实际尝试及可空用量。
默认无问题/历史/HyDE 全文日志。跨阶段关联需调用方提供 trace_id/task_id；诊断不塞入证据。

既有契约限制不变：无单路可执行计划、无成功结果 warnings/clarification、无双路不同 candidate_k、
无 RetrievalResult.source_refs/bbox、无条文存在性验证。未私加字段或伪造这些能力。
生产目录及其双索引快照同步、真实 LLM 适配器、数据政策、模型截断影响和召回收益尚未验证。

## 8. Task 6.5 启动条件

已满足：稳定公开 plan/execute、三个既有阶段串联、Hybrid 注入、可配置可测试的单文本策略、
范围保护、确定性参数映射、离线测试与全量回归。

真实评估仍需维护者确认：真实模型及数据政策、生产可信目录、语料/索引/模型快照、
可比较的 Embedding 文本预算、经人工复核的意图/过滤/相关 chunk 标签及成本依据。
没有这些依据不能报告 Recall/MRR/nDCG 或改写准确率。
本次不构建该数据集、不运行真实质量评估；提交维护者审查后停止。
