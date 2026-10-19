# Query 接口

## 职责与非职责

`plan()` 形成结构化检索计划；`execute()` 通过注入的 Hybrid Protocol 检索。
Task 6.1 Understanding、Task 6.2 Rewrite、Task 6.3 Expansion/HyDE 已实现为独立内部能力；
Task 6.4 已通过公开工厂组合这些能力，实现完整 `QueryService.plan/execute`。
本模块不创建模型 SDK、Embedding、数据库客户端，不实现 BM25、向量搜索、融合、Generation。

Task 6.5 的人工金标校验、消融和指标计算由独立 Evaluation 适配器完成，不改变这里的业务逻辑
或公共契约。使用与真实/模拟结果边界见 [评估说明](../../../../docs/task-6.5-query-evaluation.md)；
Evaluation 仅通过公开工厂、Protocol 和既有 trace 日志观测，不导入本模块 internal。

## Task 6.4：公开服务与最小调用

其他业务模块只导入 `engineering_rag.modules.query.api`；共享类型从 contracts 导入。
真实签名为：

```python
def create_query_service(
    *,
    llm: StructuredLLMClient,
    catalog: StandardMetadataCatalog,
    hybrid_service: HybridRetrievalService,
    config: QueryConfig,
) -> DefaultQueryService: ...


class QueryService(Protocol):
    def plan(self, request: QueryRequest) -> RetrievalPlan: ...
    def execute(self, request: QueryRequest) -> QueryResult: ...
```

工厂创建本模块既有三个阶段，仅接收公共依赖 Protocol；不会创建任何外部适配器。
`DefaultQueryService` 也可直接注入本模块阶段（understanding/rewrite/enhancement）、
hybrid_service 和 PlanningConfig，便于独立测试，不是第二套公共阶段 DTO。

下面是可调用的组合函数；参数实例必须由组合根提供真实实现，示例本身不提供 LLM 或生产目录：

```python
from engineering_rag.contracts.catalog import CatalogIndexScope
from engineering_rag.contracts.llm import StructuredLLMConfig
from engineering_rag.contracts.protocols import (
    HybridRetrievalService,
    StandardMetadataCatalog,
    StructuredLLMClient,
)
from engineering_rag.modules.query.api import (
    EnhancementConfig,
    PlanningConfig,
    QueryConfig,
    QueryRequest,
    QueryService,
    RewriteConfig,
    UnderstandingConfig,
    create_query_service,
)


def build_query(
    llm: StructuredLLMClient,
    catalog: StandardMetadataCatalog,
    hybrid_service: HybridRetrievalService,
    model: StructuredLLMConfig,
    scope: CatalogIndexScope,
) -> QueryService:
    return create_query_service(
        llm=llm,
        catalog=catalog,
        hybrid_service=hybrid_service,
        config=QueryConfig(
            understanding=UnderstandingConfig(llm=model, scope=scope),
            rewrite=RewriteConfig(llm=model),
            enhancement=EnhancementConfig(expansion_llm=model, hyde_llm=model),
            planning=PlanningConfig(scope=scope),
        ),
    )


# query = build_query(llm, catalog, hybrid_service, model_config, deployed_scope)
# request = QueryRequest(question="设备基础的检修空间要求？")
# plan = query.plan(request)        # 仅规划，有模型/目录调用，但无检索
# result = query.execute(request)   # 内部新规划一次 + 一次 Hybrid.search
# evidence = result.evidence       # 只有本次 Hybrid 的真实返回值
```

不要在需要“一次规划”的执行流程里先 plan 再 execute(request)：这是两次独立调用，
会重新规划。现有公共契约没有 execute(plan) 或公开计划缓存。

### 确定性映射

`Understanding → Rewrite → Enhancement → build_plan`；每阶段调用入口一次。
acquisition 仍调用 enhance 入口以取得合法跳过状态，但不会发起 Expansion/HyDE 模型调用。
execute 调用一次自身 plan，再调用一次注入的 Hybrid.search，不执行其他检索或重试。

| 目标 | 实际规则 |
| --- | --- |
| keyword.query | 主 rewritten_query 原样保留，按原顺序以换行附加已审核同义词；不含 HyDE/Expansion |
| 同义词预算 | 默认最多 4 项、单项 64 字符；空白、重复、主查询已含项不再附加；只整项舍弃，不截词 |
| vector.query / acquisition | 完整 rewritten_query |
| vector.query / exploratory | completed 且未超预算的 HyDE 优先；否则按 Expansion 原顺序取首条有效、不同于主查询且未超预算的文本；否则主查询 |
| 多扩展 | 只选一条，不拼接、不 fan-out、不按未定义分数选最佳、不做二次融合 |
| 两路文本上限 | 默认各 8192 字符；主改写超任一路预算报错，增强超向量预算整项跳过；不截断保护条件 |
| filters | 仅 Understanding 已核验结果，独立深复制到两路；检查调用方范围未扩大，后续阶段不得改变 |
| rewritten_queries | 主改写在首位，随后全部已校验 Expansion，稳定去重；该列表不是多路检索请求 |
| hypothetical_document | 已校验 HyDE 或 null；如因规划预算未被采用仍可保留，实际发送文本以 vector.query 为准 |
| intent / processing_intent | Understanding 的 semantic_intent / processing_intent，互不推断 |
| evidence | Hybrid 返回结果，保留身份、内容、标准、条文、页码、分数、顺序和 rank，不混入模型产物 |

这些字符预算不是 Embedding tokenizer 预算；Vector 仍负责 query_instruction 与编码。
Query 不重复加前缀，也不能保证长文本不会被实际 Embedding 模型截断；组合根应按模型设置
更小且经过验证的预算。上游受控生成与词表策略仍按 6.2/6.3 执行，不重写其安全规则。

### 配置、过滤与召回参数

QueryConfig 复用 UnderstandingConfig、RewriteConfig、EnhancementConfig、PlanningConfig，
必须显式提供四项；两处 scope 必须一致。配置在工厂/服务构造时校验并深复制，无导入副作用。
这些配置及 LanguageRule、EquivalentTerm、RelatedContext 都可从 query.api 导入；不是新公共契约。

PlanningConfig.scope 指定 keyword_index/vector_collection，索引不由 LLM 或查询文本选择。
candidate_k 默认 50，同时写到两个子请求 top_k；Hybrid 也会覆盖它们为此共享值。
用户唯一可映射的召回选项是 QueryOptions.top_k（默认 10），超 candidate_k 立即失败，
不静默缩小或扩大候选数。keyword_candidate_limit=100、vector_candidate_limit=64 是部署声明的
候选预算，默认兼容既有后端默认 max_top_k=100、Vector HNSW search_ef=64；candidate_k 必须
不超过两者。Query 不检查真实后端配置，组合根须确认预算与实测服务一致。

fusion_strategy 默认 FusionStrategy.RECIPROCAL_RANK_FUSION（rrf），权重仅 0.5/0.5；
可配置 FusionStrategy.WEIGHTED_NORMALIZED，有限非负权重和必须为 1。
内部严格配置的 Python 构造请使用枚举；JSON 读取可用公共枚举字符串。
embedding_model_id 默认 null，按已有 Vector 请求传递；不设置 field_weights，保留 Keyword 默认行为。
QueryOptions 没有候选数、权重或索引字段，因此这些参数来自可信配置，不私加公共选项。
RRF 平滑常量仍由 Hybrid 的配置控制，Query 不实现融合或重新归一化。

七项过滤字段保持现有语义：document_ids、standard_codes、editions、clause_numbers、
content_types（同字段 OR、跨字段 AND）、is_explanation、is_mandatory（null 不筛选）。
范围核验失败原样中止，不清空条件全库检索。catalog 的索引对必须等于真实检索索引对。

### 失败、可观测性与生命周期

QueryPlanningError.code 仅补充 unsupported_mode、invalid_parameters、invalid_upstream、
invalid_result。非法配置/公共数据结构使用 Pydantic ValidationError；UnderstandingError、
RewriteError、EnhancementInputError 与 Hybrid 原始异常不吞没、不包装成空结果。
只有 6.3 返回的合法可选阶段降级可以继续；正常零命中才返回 evidence=[]。
返回时重验公共结果；非有限分数、非 Hybrid 来源或注入服务修改提交请求均拒绝成功返回。

使用现有标准 logging，记录 trace_id/task_id、运行 ID、阶段状态/耗时、增强状态、向量策略、
candidate_k/top_k 和结果数；各模型阶段已有模型/Prompt/策略版本和可空实际 Token 用量日志。
完整链路关联请传 QueryRequest.trace；未知用量仍为 null，不计算虚构费用。
不默认记录问题、历史、增强或完整模型输入输出。公共结果无诊断字段，状态仅在私有产物/日志。

plan 无检索、无索引/文件写入，但会调用注入模型和目录；execute 增加一次只读检索。
无隐藏缓存、后台任务或检索重试；LLM 的有界重试仍由既有阶段预算控制。
同一经过验证的阶段结果产生确定计划；模型随机性、运行 ID 与耗时不承诺确定性。
服务无逐请求共享可变状态；客户端、目录、Hybrid 的关闭与线程安全由注入方负责，Query 不关闭它们。

验收、限制和 ADR-Q-004 见 [Task 6.4 报告](../../../../docs/task-6.4-retrieval-planning.md)。

## Task 6.1：内部 Understanding（已实现）

此入口供 Query 内部后续阶段与独立测试使用，不是供其他业务模块绕过公开 API 的新契约：

```python
from engineering_rag.modules.query.internal.config import UnderstandingConfig
from engineering_rag.modules.query.internal.understanding import QueryUnderstanding

# llm、catalog 由组合层通过公共 Protocol 注入；Query 不默认创建供应商或数据库客户端。
# llm_config 是 StructuredLLMConfig；scope 是 CatalogIndexScope（可信部署配置）。
understanding = QueryUnderstanding(
    llm=llm,
    catalog=catalog,
    config=UnderstandingConfig(llm=llm_config, scope=scope),
)
result = understanding.understand(request)  # QueryRequest -> UnderstandingResult
```

输入复用 QueryRequest，问题不可空白；不截断原问题。默认预算：问题 8000 字符、历史
8 条/合计 16000 字符、每项列表过滤 32 值、目录最多 128 次查询，超限明确失败。
`max_attempts=2`（可设 1），输出纠正与超时/连接重试共享预算；适配器必须遵守
StructuredLLMConfig 的超时/token 预算且不得内部隐藏重试。本阶段不执行 mode/top_k 检索。

输出是严格的私有 Pydantic 类型，包含 processing_intent、新 SearchFilters、索引对 scope、
完整 catalog_matches（含目录/快照/测试标记）、decisions（候选及原文区间、采用/拒绝/忽略原因）、
attempts（请求 ID、耗时、状态、可空用量）、diagnostics/degraded、模型/配置/提示版本。
semantic_intent 保持 unknown；clause_existence_verified 始终 false。结果可 JSON 往返。

调用流程：结构化 LLM → validate_output → 原文证据核对 → validate_for 目录核验 → 范围求交。
两类处理意图由结构化模型决定，不用关键词代替理解；本地词形检查仅用于过滤候选证据。
模型不允许输出 document_id。代码/名称/可信别名/版次/修订经目录解析成已入库文档身份；
多个标准分别验证，用 document_ids 保留标准与版次的配对。调用方提供的文档/标准范围也核验，
已核验的调用方唯一文档可以消除版本歧义。仅有 edition 的调用方过滤可保留，但不构成身份证明。

证据使用 Python 字符偏移 [start,end)，quote 必须与原始用户文本完全一致，候选值须位于
对应证据中。不得拼接不同轮次的标准属性；助手历史不是可信范围。保守首版不自动采用历史
推断的精确过滤：本轮有范围则忽略旧候选并留诊断，仅有历史标准而无明确/已验证范围则要求
澄清。模型遗漏明显标准代码时拒绝无约束成功；该 guard 不是完整标准注册表。

列表同字段 OR、跨字段 AND，与已有条件求交，空交集报错；布尔 null 不筛选，不等于 false。
只有明确的“条文说明/强制性条文”等证据才能产生对应筛选，不根据应/必须推断强制性。
条文只验证格式、原文和文档范围，不验证存在性。输入及调用方 filters 不被修改。

错误：内部 `UnderstandingError.code` 区分 input_budget、invalid_output、invalid_evidence、
model_failure、unmatched_scope、ambiguous_scope、catalog_unavailable、scope_conflict。
错误附 attempts/decisions/catalog_matches，真实异常通过 __cause__ 保留。失败不生成成功结果，
也不通过清空 filters 降级。测试目录默认拒绝，仅离线测试显式 allow_test_catalog=True。

副作用仅限注入能力的有界调用；不读写索引/文件、不连接数据库，不默认记录问题或历史。
相同候选和目录快照下范围合并稳定；模型输出、随机关联 ID 和耗时不承诺逐字一致。
服务不持有逐请求可变状态，配置深拷贝；客户端和目录的生命周期/并发安全由注入方负责。
私有结果含原文证据，应受控保存，不应当作普通日志输出。

实际实现、保守策略及离线验收见
[Task 6.1 说明](../../../../docs/task-6.1-query-understanding.md)。

## Task 6.2：内部 Rewrite（已实现）

仅供 Query 内部协作和独立测试，不是新的跨模块公共契约：

```python
from engineering_rag.modules.query.internal.rewrite import QueryRewrite
from engineering_rag.modules.query.internal.rewrite_models import RewriteConfig

# llm: 注入的 StructuredLLMClient；llm_config: 已批准的 StructuredLLMConfig。
# request 与 understanding_result 必须对应同一次 Understanding，不能拼接不同请求的结果。
rewriter = QueryRewrite(llm=llm, config=RewriteConfig(llm=llm_config))
result = rewriter.rewrite(request, understanding_result)
# result.original_question 原样保留；result.rewritten_query 为唯一主查询。
# result.keyword_synonyms 允许为空；result.filters 是 Understanding.filters 的独立深拷贝。
```

真实签名：`rewrite(QueryRequest, UnderstandingResult) -> RewriteResult`。复用 Task 6.1 的实际
结果类型，不重新理解、查目录或修改其输出。输入类型、已有 filters 的收窄关系、采用候选的
原问题证据及明显的标准/版次/条文冲突先检查；冲突在调用模型前失败。Understanding 当前没有
原始请求摘要，调用方仍须保证结果来自同一次请求，局部一致性检查不是跨请求身份认证。

模型请求 stage=query_rewrite，携带原问题、有界带 role 历史、处理意图、既有验证范围、保护值、
受信任规则与词表，使用私有 RewriteOutput 生成 Schema，再执行 response.validate_output。
输出只允许 rewritten_query（非空白）和 keyword_synonyms（字符串候选列表），不能返回新过滤。
获取性与探索性在这里执行相同的基础改写；不回答问题、不生成扩展、HyDE 或查询计划。

安全门包括标准身份/名称/版次/修订、定位编号、数值精度与单位、变量/LaTeX/Unicode 数学符号、
否定/规范强度/条件与比较词的有序保护；在问题中出现的已核验目录名称、别名等也受保护。
除此之外，主查询必须能由原文逐字复制及经审核的局部 language_rules 构成。记录每个修改的
原文字符区间、替换及 evidence_id；不允许仅凭模型声明保真，不允许重排技术对象或自由补词。
默认规则仅处理少量口语与明确普通错字；可能正确但无法证明的自由改写也会拒绝。

同义词默认不猜测（equivalent_terms=[]）。如需补充，注入经维护者审核的
`EquivalentTerm(term, equivalent, evidence_id)`；模型建议必须与此词表精确匹配，且原词在
当前问题中出现。丢弃空白、重复、未验证、上下位/仅相关候选及编号/答案/约束词，记录原因；
最多保留 4 个、每个 64 字符，可配置。词表是可信配置，不是模型自称的置信度或权威目录；
错误的人工等价断言不能靠此机制自动纠正，不应配置含歧义的跨场景同义词。

本阶段不提供 keyword_query：已检查 Keyword 接收普通文本字符串，实际拼接由 6.4 Planning 完成；
本阶段只输出主查询与审查后的少量同义词，不生成 DSL、不修改或调用任何检索模块。

预算默认：原问题 8000 字符，历史最多 8 条/16000 字符，主查询 8000 字符，最多 2 次尝试
（可设 1）。不截断当前问题或历史来伪称完整理解；超时/连接失败、Schema 纠正及安全纠正
共享预算，最多一次额外尝试，其他供应商异常不重试。适配器负责真实调用的超时/token 限制，
不得隐藏重试。安全对齐最多 50000 个状态，词表/规则/原始同义词候选也有数量上限。

`RewriteError.code` 区分 input_budget、scope_conflict、invalid_output、unsafe_rewrite、
model_failure；保留 __cause__ 和私有 attempts。耗尽预算必须失败，**不返回原问题伪装成功**。
正常无须修改的问题可以由合法模型响应原样返回，仍必须通过全部校验；这不是异常回退。

RewriteResult 还包括 processing_intent、完整保护区间、局部修改 lineage、同义词审查记录、
模型尝试（状态/耗时/可空用量）、trace、提示/模型/配置版本及策略指纹；支持严格 JSON 往返。
默认 INFO 日志只记录阶段、关联 ID、状态、预算次数、用量与版本，不写问题/历史/模型全文。
私有结果和异常链仍可能包含敏感原文，应受控使用。无文件/数据库副作用、无真实 SDK，
输入/Understanding/config 均隔离复制；注入客户端的生命周期由组合层管理。

Task 6.3 已按下节入口消费唯一 rewritten_query、可信 keyword_synonyms、处理意图及
未变化的 filters，并继续保留原 QueryRequest/Understanding。Rewrite 策略、限制和实测结果见
[Task 6.2 / ADR-Q-002](../../../../docs/task-6.2-query-rewrite.md)。独立测试：

```bash
python -m pytest src/engineering_rag/modules/query/tests/test_rewrite.py -q
python -m pytest src/engineering_rag/modules/query/tests -q
```

## Task 6.3：内部 Expansion / HyDE（已实现）

```python
from engineering_rag.modules.query.internal.enhancement import QueryEnhancement
from engineering_rag.modules.query.internal.enhancement_models import EnhancementConfig

# llm 为注入的 StructuredLLMClient；两份配置使用已有 StructuredLLMConfig。
enhancer = QueryEnhancement(
    llm=llm,
    config=EnhancementConfig(expansion_llm=expansion_llm_config, hyde_llm=hyde_llm_config),
)
result = enhancer.enhance(request, understanding_result, rewrite_result)
```

真实内部签名：`enhance(QueryRequest, UnderstandingResult, RewriteResult) -> QueryEnhancementResult`。
三个输入必须来自同一流程；检查原问题、处理意图、filters、trace、成功 Rewrite 状态及原文
保护区间的一致性，不重跑理解/改写、不查目录。不序列化整份请求、历史或目录到模型输入。
输入或上游关系错误抛 `EnhancementInputError`（invalid_upstream/input_budget），不是可选降级。
不合法配置或关联集合在构造时以 ValueError/ValidationError 拒绝，不降级掩盖配置错误。

| ProcessingIntent / 开关 | 实际调用与状态 |
| --- | --- |
| acquisition | 两阶段均零调用，skipped_by_intent；不依据关键词或问题长度重分类 |
| exploratory + 开启 | 分别调用 query_expansion / query_hyde，各自 Schema、绑定与安全校验 |
| exploratory + 关闭某阶段 | 对应阶段零调用，skipped_by_config，不视为失败 |
| 某阶段失败 | 对应 failed，无伪造产物；另一阶段仍正常尝试，保留安全主查询/同义词 |

ExpansionOutput 只允许 expanded_queries；HyDEOutput 只允许 hypothetical_document。
两者均由 Pydantic 生成 Schema，并必须执行 response.validate_output；没有直接使用 data。
默认每阶段一次正常调用，无重试。可配置 max_corrections=1，为两阶段共享一次额外纠正，
包括超时/连接、Schema 和安全失败；全程最多三次调用，不能叠加独立重试。其他模型异常不重试。

当前是**受控生成**：扩展逐字保留完整主查询，再以独立“检索关注”标签附加已审核的相关概念；
HyDE 使用明确的假设/非证据框架，保留完整查询约束，可选择同一审核集合中的检索语境。
默认提供设计、规范、比较三类通用检索视角，也可通过 RelatedContext(anchor, phrase, evidence_id)
注入已审核的关联概念。它们不是同义词、事实或新增设计前提；词表本身是可信配置，非权威目录。
新编号、取值、引用、条件改动、对象交换、非审核文本等均拒绝；自由长段落即使看似合理也可能
被拒绝。不能仅凭这些离线安全门声称真实模型语义准确或召回提升。

默认最多 3 条有效扩展、每条 2048 字符，HyDE 4096 字符/最多 3 个语境；原问题和主查询各
8000 字符。只裁减超数量的候选并记录原因，不截断主查询或长候选来伪称保真。空扩展列表
为 completed；重复主查询/重复候选稳定去重；全部实质候选不安全则 failed，部分拒绝或预算
裁减标记 degraded。原始模型候选另有 16 条/每条 16000 字符的硬 Schema 上限。

结果私有 schema_version=1.0，包含 original_question、rewritten_query、keyword_synonyms、
processing_intent、filters 的独立副本、expanded_queries、可空 hypothetical_document、
expansion_status/hyde_status、两个 StageReport、degraded、trace 与策略指纹。
StageReport 包含模型/提示/配置版本、每次请求 ID/耗时/用量/错误类别及候选采用诊断；未知用量
为 null。状态与产物有一致性校验，hypothesis_is_evidence 固定 false；支持 JSON 往返。
模型失败类别为 timeout、connection、model_failure、invalid_output、unsafe_output；不写原始
问题、历史或模型全文到普通日志，不把可选失败伪装成检索成功或检索失败。

关键词基础只来自未变化的 rewritten_query 和 keyword_synonyms；增强材料保存在独立字段，
不拼入 BM25、不改 filters、不转为 Document/Chunk/evidence/引用。没有 keyword_query、
vector_query、Embedding 或任何实际检索调用。

实际 VectorSearchRequest.query 是单字符串，HybridSearchRequest 只有一个 vector 子请求；
RetrievalPlan.rewritten_queries 是计划数据列表，不是向量多查询能力。Task 6.4 已按上节选择并
测试有界单文本策略；本增强阶段本身不拼接最终文本、不组装请求、不 fan-out，
不修改 Vector 的 query_instruction。

本入口仍只供 Query 内部集成。具体受控格式、信任边界和验收见
[Task 6.3 / ADR-Q-003](../../../../docs/task-6.3-query-enhancement.md)。独立测试：

```bash
python -m pytest src/engineering_rag/modules/query/tests/test_enhancement.py -q
python -m pytest src/engineering_rag/modules/query/tests -q
```

## 公开接口

导入路径：`engineering_rag.modules.query.api`。

```python
class QueryService(Protocol):
    def plan(self, request: QueryRequest) -> RetrievalPlan: ...
    def execute(self, request: QueryRequest) -> QueryResult: ...
```

输入 QueryRequest 保持原字段：question、history、filters、options、trace；
QueryOptions 仍接受 keyword/vector/hybrid，默认 hybrid，top_k 默认 10。

RetrievalPlan 使用 Literal `schema_version="2.0"`，含 original_question、rewritten_queries、
hypothetical_document、原有语义 intent、**必填 processing_intent**、retrieval_mode、
hybrid_request。语义 QueryIntent 五类保持不变；ProcessingIntent 只接受 acquisition/exploratory，
缺失、null 或 unknown 都拒绝，不能根据旧 intent 猜测。

QueryResult 使用 Literal `schema_version="2.0"`，仍只有 plan 与 evidence；evidence 内
RetrievalResult 保持检索 1.0。没有新增 warnings、clarification 或其他结果字段。

两路查询分别在 hybrid_request.keyword.query 与 vector.query；它们可不同，过滤按同一已验证
范围复制。candidate_k 仍是每路共享召回数，Hybrid 覆盖子请求 top_k；最终 top_k 独立。
RRF 公共权重只允许 0.5/0.5，可变权重使用 weighted_normalized。详见 Hybrid 接口。

## 失败与执行语义

首版仅支持 hybrid；keyword/vector 是合法 DTO 值，但服务在模型调用前抛
QueryPlanningError(unsupported_mode)，不自动改 mode 或用零权重模拟。

LLM 只能抽取候选；格式与原文依据验证后，以可信目录匹配标准/版本/document_id。
显式范围不得扩大；交集为空须报 scope conflict，不能传空数组解除限制。未匹配、歧义、
目录不可用、输出非法、模型失败、Hybrid 失败均走明确异常，保留原因，不伪装空 evidence。
Understanding 已使用上述最小异常体系；检索执行错误原样传播。

plan 不检索，但会产生有预算的 LLM 调用；execute 只读检索，不写数据库。
相同模型输入不承诺逐字确定，需记录配置与提示版本。当前 Protocol 没有 execute(plan)，
外部先 plan 再 execute(request) 可能重新规划。

## 依赖、版本与示例

跨模块依赖唯一来源是 engineering_rag.contracts。query.api 重导出 QueryService、ProcessingIntent、
QueryIntent、QueryRequest/Result、RetrievalPlan、StructuredLLMClient、StandardMetadataCatalog
以及两个迁移函数，并暴露上述配置、DefaultQueryService 与 create_query_service。
Query 内不得导入其他业务模块的具体实现、internal 或数据库客户端。

依赖能力契约（Query 只依赖声明，不在模块内创建真实适配器）：

```python
class StructuredLLMClient(Protocol):
    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse: ...


class StandardMetadataCatalog(Protocol):
    def lookup(self, request: StandardMetadataLookup) -> StandardMetadataMatch: ...
```

LLM 请求携带 stage、JSON input、Pydantic 模型生成的 output_schema、模型配置、超时、
Token 预算和可空 trace；响应的 data 必须经 validate_output(request, OutputModel) 才能
作为结构化业务 DTO 使用。OutputModel 必须 extra=forbid；未知用量为 null，不伪造零。
ValidationError/ValueError 表示输出或绑定校验失败；未来适配器须明确传播调用/超时/连接错误。
端点和密钥由基础设施适配器管理，不在 DTO 中；本模块没有 SDK、模型下载或直接网络调用。

目录 Lookup 按标准代码/名称/别名、版次/修订或可信显式 ID 查询指定双索引范围，Match 返回
unique/ambiguous/not_found/unavailable、catalog_id/snapshot_id 和 is_test_fixture。
调用方使用 validate_for(request) 校验请求、范围与候选映射；global record 不代表已入库。
目录不支持条文存在性验证。离线夹具在契约/Query 测试中，不能用于生产过滤。

详细字段、验证规则和未决事项见 [ADR-Q-001](../../../../docs/adr-task6-query-prerequisites.md)。

## 版本与显式迁移

QueryService 方法签名不变；计划/结果序列化升级到 2.0，QueryRequest、检索 1.0、Document
Frozen 2.4 不变。旧严格消费者无法读取新字段，升级需协调调用方。

```python
from engineering_rag.contracts import ProcessingIntent, migrate_query_result_v1

# 接口示例：legacy_payload 是解析后的 V1 JSON，decision 来自明确的人工/应用决定。
decision = ProcessingIntent.ACQUISITION
# result_v2 = migrate_query_result_v1(legacy_payload, processing_intent=decision)
```

另有 migrate_retrieval_plan_v1(payload, *, processing_intent)。缺少或非法处理意图时拒绝，
不做自动推断；原语义意图、请求和证据保留。迁移函数只返回新模型，不覆写旧文件。
新读取器不自动接受 V1；更高/未知版本和混合新旧字段拒绝。

```python
# query_service 使用上文工厂构造；以下调用真实存在。
# plan = query_service.plan(request)  # 不检索
# result = query_service.execute(request)
```

独立测试：`python -m pytest src/engineering_rag/modules/query/tests -q`。

新增契约测试：

```bash
python -m pytest tests/contracts/test_query_v2.py tests/contracts/test_structured_llm.py \
  tests/contracts/test_metadata_catalog.py -q
python -m pytest tests/architecture -q
```

合法虚构 JSON 见 examples/query_result.v2.example.json；不是实际 Query 执行结果。
Task 6.6 已提供基础设施 OpenAI-compatible 适配器（DeepSeek 配置）、只读双后端语料校验目录和
真实组合 CLI；它们不是 Query 的隐式默认依赖。目录只覆盖经核验的单文档快照，不是全局目录
或自动刷新服务。调用方式、数据传输与真实验证状态见
[Task 6.6](../../../../docs/task-6.6-real-query-smoke.md)。完整 LLM 链路仍需有效密钥后实际验收。

