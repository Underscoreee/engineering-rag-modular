# Task 6.3：Query Expansion / HyDE 实现与验收

日期：2026-10-18。范围仅为 Query 内部可选增强，无真实模型/数据库调用，不实现 Task 6.4。

## 1. 基线与前序事实

工作区初始干净，HEAD `31d7002`。实际运行完整基线：**674 passed、24 skipped，11.12 秒**，
没有 Parser 路径收集阻塞。已完整阅读任务书、AGENTS、Query 接口及 Task 6.0 设计/ADR，
核对现有 Understanding、Rewrite、LLM 绑定验证、ProcessingIntent 与检索契约代码。

实际输入：QueryRequest、UnderstandingResult、RewriteResult。前序能力已实现，不创建
第二套同名 DTO，不重跑意图/目录/改写。Rewrite 已验证 filters、处理意图及原文保护信息可
直接消费；只检查对应关系和输入预算，不从增强文本识别或建立新的过滤范围。

VectorSearchRequest.query 是 NonEmptyStr，HybridSearchRequest.vector 是单个子请求，没有
多向量查询列表。RetrievalPlan.rewritten_queries 虽是列表，只是计划产物，不授权多路召回。
公共 Query 2.0、Document Frozen 2.4 和检索契约都不变。

旧 Task 6.0 业务流为历史建议；本任务明确禁止把 Expansion 自动加入关键词，也禁止提前
生成最终向量文本。因此这两个动作没有在本阶段实施。

## 2. 入口、输入和结果

```python
from engineering_rag.modules.query.internal.enhancement import QueryEnhancement
from engineering_rag.modules.query.internal.enhancement_models import EnhancementConfig

# 接口示例；llm 和两份模型配置由组合层注入，没有默认真实 SDK。
service = QueryEnhancement(
    llm=llm,
    config=EnhancementConfig(expansion_llm=expansion_config, hyde_llm=hyde_config),
)
result = service.enhance(request, understanding, rewrite)
```

`enhance(request: QueryRequest, understanding: UnderstandingResult, rewrite: RewriteResult)
-> QueryEnhancementResult` 是 Query 内部入口，不是新增跨模块 API；query.api/Protocol 不变。
它只取必要字段，既不向模型复制整个上游产物，也不发送完整请求/history/catalog。

路由只依据已验证 ProcessingIntent：acquisition 均 skipped_by_intent、零调用；exploratory
按两个独立开关分别执行，关闭为 skipped_by_config。文本长短、比较关键词、关注概念锚点
不参与意图重分类。开关关闭或按意图跳过不是失败，也不制造空洞产物。

QueryEnhancementResult 为版本 1.0 的私有模型：原问题、主查询、关键词同义词、意图、filters
隔离副本、扩展列表、可空假设文档、两个阶段状态/报告、degraded、trace、策略指纹。
hypothesis_is_evidence 永远 false。报告中有模型/配置/提示版本、请求 ID、每次尝试耗时与
可空 Token 用量、失败类别和 Expansion 候选诊断。模型校验状态与产物的一致性并支持 JSON 往返。

上游不匹配/不是成功 Rewrite、保护区间不符、非法意图或输入超限在任何增强调用前抛
EnhancementInputError；这不能通过可选降级掩盖。原始请求、两份上游产物和构造配置均不被修改。

## 3. ADR-Q-003：受控生成、相关性证据与保真边界

- 状态：本任务采纳的内部实现策略，不变更公共契约。
- 问题：只验证编号集合不能证明比较对象、条件归属或任意生成段落保真；工程术语、模型
  自称相关/安全或高置信度都不能代替证明。本阶段没有新 NLP 模型、真实审核器或事实库。
- 选择：默认只接受**完整主查询锚点 + 审核关联概念**的受控格式，拒绝无法证明的自由生成。
  模型仍必须真实通过注入接口返回产物，应用只验收，绝不在失败后自行填造生成内容。

### Expansion

每条候选格式为：

```text
<完整 rewritten_query，逐字不变>
检索关注：<审核过且与主查询存在锚点关系的 phrase>
```

主查询整体保留，避免只检查 token 存在却允许数值/对象/否定关系互换。关注点明确是检索视角，
不是新增适用条件或同义替换。默认集合是三类通用检索关注：设计条件与验算要求、规范范围与
条文联系、比较对象的条件与差异，分别要求主查询含相应锚点。可用 RelatedContext 注入
经审核的关联概念。复用既有字词边界纯工具，避免将拉丁缩写从另一个变量中截取。

模型返回 expanded_queries，由严格 ExpansionOutput 校验后逐条审查。默认最多接受 3 条，
每条 2048 字符；顺序保留，重复稳定去重。显式空列表正常 completed；只有重复主查询也可
completed/空产物。非空列表全部实质候选不安全时 failed；混合候选保留有效者，拒绝项留下
索引/尝试编号/原因/审核 ID。超过接收数量的候选不进入产物并标记降级，不裁掉主查询条件。

### HyDE

HyDEOutput 只允许一条有限字符串。当前受控格式为：

```text
假设性检索材料（非规范证据）
查询约束：<完整 rewritten_query>
检索语境：<审核关联概念，可省略或出现多行>
仅用于语义检索，具体要求待真实证据核验。
```

完整锚点锁定全部条件，额外语境只能来自当前可用审核集合，不能有重复、超过数量或新增
自由事实/取值/来源。允许没有额外语境，但整份文档仍须由模型明确输出并通过格式校验；
默认 4096 字符、最多 3 个语境，不截断后伪称完整。语境解析以完整锚点长度为边界，原问题
自身出现“检索关注”等标签也不能逃出约束区。没有拼接 Expansion 产物、没有构造最终向量查询。

这是一份保留条件、标为待核验的假设性检索描述，**不是自由预测规范答案，也不是规范证据**。
即使输入本身含标准代码/数值，也只是用户约束，不因进入 HyDE 成为经证实的规范取值或引用。
不生成新标准、定位符、参数、公式或出处，不落到 Document、Chunk、Golden 或 evidence。

### 信任边界与代价

关联集合是可信配置，不是模型自己输出的“证据”。配置结构及基础防护拒绝数值、变量/定位符、
来源/规范断言、扩大全库或声称等价的表达；模型无法自行扩充集合。关联关系的科学适用性仍须
维护者审核，evidence_id 本身不是权威证明。这里不创建生产目录，也不把相关关系当作等价关系。

代价是会拒绝许多可能合理的自由扩写/自由 HyDE，默认关注集合覆盖面有限。相较于任意自然
语言生成，受控格式可能降低增强效果；没有真实模型/人工标注或召回实验，不能声称效果提升。
扩大覆盖须先提供可审核的语义依据，不能为了通过测试放开保护门或用生成文本证实自身。

## 4. 独立调用、预算与降级

两个阶段分别使用 query_expansion/query_hyde、各自模型配置/输出 Schema，调用
response.validate_output 校验请求 ID、模型及显式 revision、对应 Schema，然后安全验收。
请求只含原问题、主查询、已验证意图/filters、必要保护值、审核集合与预算；不含全部历史。
Expansion 与 HyDE 不以彼此输出作为输入，因此前者失败不会污染或阻止后者。

默认各一次普通调用、零纠正；max_corrections 可设严格整数 0 或 1，两阶段共享同一个额外
预算，最多 3 次 generate。Schema/安全/超时/连接故障可以消耗该额度，其他模型错误不重试。
一个阶段用完纠正后另一个仍有自己的首次调用，不会因“总次数耗尽”而被错误跳过。
底层适配器必须遵守已有超时/Token 配置，不得隐藏重试；同步 Protocol 不能强行终止失约客户端。

失败返回对应 failed 状态及 timeout/connection/model_failure/invalid_output/unsafe_output
类别；无伪造产物、无静默成功。可选模型失败采用状态式降级而不是沿用 Rewrite 的必需阶段
失败政策。错误摘要不记录原异常全文，避免泄露问题或模型输出。两者均失败时 degraded=true，
主查询、可信同义词和 filters 仍完整可用，不把这解释成检索成功或正常无命中。

所有用量来自响应，未知保持 null；报告尝试耗时涵盖模型调用与输出验收，可按尝试求和。
INFO 日志记录 trace/task/request、意图、阶段/状态/降级、数量、模型配置、耗时/用量与版本，
不新增日志框架、不写问题/history/模型全文、不自动输出异常链。私有结果仍有敏感文本，应受控。

## 5. 关键词隔离与 Task 6.4 约束

关键词基础只保留 Rewrite.rewritten_query 与 Rewrite.keyword_synonyms，未被增强覆盖。
expanded_queries 和 hypothetical_document 为独立字段，没有 keyword_query/vector_query、
Embedding、最终检索请求或检索调用；filters 只做深拷贝，不能从生成内容增删任何值。

实际检索只有一个向量 query 字符串。Task 6.4 须独立批准并测试选择/有界组合策略，例如
有效 HyDE 优先，HyDE 不可用时用有效扩展，最后使用安全主查询；它也可以依据评估选择其他
策略，但本阶段没有预先实现任何一种。不能把计划列表误当作多向量接口，也不能擅自 fan-out、
修改 Hybrid 融合或 Vector.query_instruction。严格保存原范围与主问题优先，防止长增强挤掉约束。

## 6. 测试与范围核对

先增加测试运行，实际出现 1 项预期收集错误：尚无 enhancement 入口；随后实现并通过。
全部使用离线 Fake LLM 与前序测试夹具，没有真实模型、数据库或生产目录调用。
覆盖路由、独立开关、非法上游、空/重复/超量/超长候选、相关性/等价混淆、标准与精度/单位/
公式/图表/否定/比较对象保护、伪造 HyDE 来源与参数、阶段独立失败、共享纠正、日志、
只读输入、模型篡改请求副本、JSON 往返和状态/证据一致性。

架构测试保留原门槛并增加增强入口签名验证，禁止增强文件调用 understand/rewrite/lookup、
Embedding/索引/检索或导入最终请求/计划/真实证据/Document/Chunk 类型，不放宽原有业务边界。

项目现有 `.venv` 内最终实际结果（全部 0 failed）：

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest src/engineering_rag/modules/query/tests/test_enhancement.py -q` | 107 passed，2.86 秒 |
| `.venv/bin/python -m pytest src/engineering_rag/modules/query/tests -q` | 285 passed，4.84 秒 |
| `.venv/bin/python -m pytest tests/contracts -q` | 175 passed，1.45 秒 |
| `.venv/bin/python -m pytest tests/architecture -q` | 9 passed，1.59 秒 |
| `.venv/bin/python -m pytest -q -rs` | 781 passed、24 skipped，9.91 秒 |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 通过 |
| `git diff --check` | 通过，无输出 |

其他六模块分别执行 `.venv/bin/python -m pytest src/engineering_rag/modules/<模块>/tests -q`：
Parser 170、Chunking 36、Keyword 30、Vector 9、Hybrid 34、Generation 1，均 passed。
Generation 的一项仍仅是已有 Protocol 测试；contracts 中 JSON 示例/Pydantic 校验没有回归。

24 项 skip 与基线一致：原 PDF 审计 1、Elasticsearch 1、MinerU 实产物/回放 19、真实 Chunking 1、
Embedding smoke 1、Milvus 1，均缺少启用变量、PDF 路径或服务 URI。本次不启用这些外部测试，
不能将 skip 视为通过；新增增强测试全部执行且没有 skip/xfail。

diff 已核对：只新增下列 7 个文件、修改 2 个文件；公共契约、前序实现、依赖及其他模块无变化。
结论：**Task 6.3 受控版本实现与离线验收 PASS**；自由生成覆盖率、真实模型与检索收益尚未验证。

新增：

- `src/engineering_rag/modules/query/internal/enhancement.py`：路由、上游一致性及统一结果/日志。
- `src/engineering_rag/modules/query/internal/enhancement_models.py`：严格私有模型、配置、状态及错误。
- `src/engineering_rag/modules/query/internal/enhancement_prompts.py`：两个版本化提示及受控格式。
- `src/engineering_rag/modules/query/internal/enhancement_runner.py`：独立结构化尝试、预算与阶段诊断。
- `src/engineering_rag/modules/query/internal/enhancement_validation.py`：关联/保真与生成产物验收。
- `src/engineering_rag/modules/query/tests/test_enhancement.py`：离线正反测试。
- `docs/task-6.3-query-enhancement.md`：本报告与内部 ADR。

修改：Query INTERFACE.md、tests/architecture/test_query_dependency_contracts.py。
公共 contracts、Task 6.1/6.2 业务实现、api.py、依赖文件和其他模块均保持不变。没有自动 Git 提交。

## 7. 未验证事项与下一阶段门槛

真实 LLM、模型安全/质量、人工 Query 金标、实际 Embedding/检索收益均未验证，不虚报准确率。
受控形式不能代替完整工程语义审核；关联集合的真实性由可信注入方保证。上游类型仍没有端到端
请求签名，局部一致性不等于跨请求认证，组合层必须正确传递对应的已成功阶段对象。

Task 6.4 需要维护者验收并明确启动，再实现公共 QueryService 的 Planning/Execution 和单文本
策略，注入已有 Hybrid Protocol。真实实验另需适配器、数据政策、索引快照及人工标注；本任务
既不构建这些基础设施，也不提前开发后续阶段。
