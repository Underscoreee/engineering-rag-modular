# Task 6.1：Query Understanding 实现与验收

日期：2026-10-18。基于 [ADR-Q-001](adr-task6-query-prerequisites.md) 的现有公共契约，
只实现 Query 内部 Understanding，不实现 QueryService、改写、Expansion、HyDE 或检索调用。

## 1. 入口、职责与数据流

`modules/query/internal/understanding.py`：

```python
QueryUnderstanding(*, llm: StructuredLLMClient,
                   catalog: StandardMetadataCatalog,
                   config: UnderstandingConfig)
understand(request: QueryRequest) -> UnderstandingResult
```

公共 API/Protocol 不变。入口暂只供 Query 内部后续集成使用，不鼓励其他模块依赖 internal。
配置与请求深拷贝，不修改调用方对象；无导入时副作用，无模型 SDK、数据库客户端或新增依赖。

| 阶段 | 实际职责 |
| --- | --- |
| 输入保护 | 重新校验请求；拒绝空白/超预算问题或历史、非法条文格式和超长过滤列表 |
| 结构化理解 | stage=query_understanding；原问题、保留 role 的有界历史、现有 filters、版本化提示及 Pydantic output_schema |
| 输出绑定 | response.validate_output；拒绝缺字段、未知字段、非法两类意图、伪造 ID、错误请求/模型/显式 revision |
| 证据审查 | 原始字符区间与 quote 一致、值在 quote 内、历史必须为用户消息，标准属性不可跨轮拼接 |
| 目录核验 | 每次唯一 request_id；可信配置 scope；match.validate_for；区分四态；拒绝测试源或跨快照混用 |
| 过滤合并 | 文档身份约束标准/版本配对；列表求交、布尔冲突拒绝；返回新 SearchFilters |
| 审计结果 | 候选采用/拒绝/忽略及原因、目录完整响应、模型尝试/用量/耗时、提示/模型/配置版本、降级诊断 |

内部文件职责：models 定义严格 DTO；config 定义预算；prompts 提供理解提示；evidence 核对来源；
scope_validator 负责可信目录；filter_merger 处理 OR/AND 范围；errors 提供单一类型化阶段异常。

## 2. 本阶段内部策略决策

这些是内部保守实现选择，不更改或扩展 ADR-Q-001 的公共契约。

1. **两类意图只取结构化模型判断。** 获取性包括复杂但目标明确的查询，探索性包括多标准比较
   和多条件关联。保留旧语义 QueryIntent.UNKNOWN，不将两种意图映射。context_sufficient=false
   要求澄清。离线替身验证控制流与边界，不证明真实模型的分类准确率。
2. **有证据不等于事实已核实。** 值必须有原文依据，标准/版本必须再经可信目录精确映射。
   document_id 仅由目录或调用方提供，模型 Schema 中无此字段。字段别名与版次不做猜测性规范化。
   当前文本中的常见大写标准代码若被模型遗漏则拒绝继续；guard 不是完整的标准名实体检测器。
3. **历史不自动成为精确范围。** 历史可辅助模型理解，但历史过滤候选记录为 ignored；当前
   明确范围优先。仅有历史标准、又没有本轮标准或已有可核验范围时，报 ambiguous_scope。
   不把助手历史或模型自行声称的“明确条件”当成可信依据。复杂指代解析留待另行授权与评估。
4. **调用方范围同样核验。** 文档 ID 逐个查目录；标准代码逐个查，可与 edition 的 OR 集组合，
   但每个显式代码及版次必须至少有在库身份支持。标准未指定版本且无法唯一匹配时失败。
   已验证的唯一调用方文档可为模型候选消歧。仅 edition 过滤保留其原有 AND 语义，不宣称
   证明了标准身份；条文过滤则必须有已验证文档范围。
5. **不产生版本交叉污染。** 多标准各自匹配后用 document_ids 限制最终集合；代码/版次列表
   不能替代文档配对。同字段 OR，跨字段 AND，与原过滤只求交，不扩展。部分 OR 候选未进入
   交集时记 rejected；空交集、布尔冲突中止，绝不以空数组解锁全库。
6. **不冒充条文权威校验。** 条文仅查格式、用户证据和文档范围，结果中
   clause_existence_verified 永远 false。is_mandatory 只表达检索既有标记的条件，不判定强条。
   内容类型/布尔证据要求最小明确语义词，不根据“应/必须”推断；不支持的表达保守拒绝。
7. **有限执行。** 结构化纠正与传输超时/连接重试共享最多 2 次尝试，其他模型异常不重试。
   纠正请求携带 previous_error 错误码，不回填未验证输出或异常原文。目录不重试，最多
   128 次查询；问题 8000 字符，历史 8 条/16000 字符，过滤每项列表 32 值，均可配置。
   问题/历史超限直接失败，不截断后伪称完整理解。实际调用超时/token 限制须由注入适配器执行，
   同步 Protocol 无法强行中止一个不遵约的阻塞客户端；适配器不得隐藏额外重试。

## 3. 失败与追踪

`UnderstandingError` 的 code 分别为 input_budget、invalid_output、invalid_evidence、model_failure、
unmatched_scope、ambiguous_scope、catalog_unavailable、scope_conflict。真实异常保留 __cause__，
私有 attempts、decisions、catalog_matches 可供受控诊断；失败时未成功应用的候选记 rejected。
没有新增公共错误 DTO，没有将失败转为空结果。错误摘要不包含问题/历史，原异常和私有证据
仍可能含敏感数据，调用方不得不加控制地记录整个异常链或结果。

本模块没有默认日志、文件写入、真实模型客户端或生产目录。关联请求 ID 与耗时会变化；在
候选与目录快照固定时过滤求交顺序稳定。未知 token 用量为 null，不伪造为零。测试目录必须
显式 allow_test_catalog=True，默认拒绝；该标记并非生产源真实性鉴定器，注入方仍须可信。

## 4. 测试及边界

测试仅使用虚构标准与注入式离线替身，覆盖二分类、范围/版本、别名、标准遗漏、证据伪造、
助手历史、跨轮混合、目录请求/入库范围/身份绑定、快照切换、部分 OR 交集、空交集、
三态布尔、重试共享预算、输入/工作量预算、未知/已知用量、JSON 往返和不泄漏普通日志。

开发前基线：完整 pytest **497 passed、24 skipped**（6.11 秒），工作区干净。
先新增测试后运行出现新内部入口不存在的收集错误；实现后离线用例通过。
现有架构测试中 6.0.1 的“internal 只能为空”阶段断言被实际复现为失败，随后替换为更符合
6.1 授权的 AST 门槛：禁止 plan/execute/后续增强或检索调用，允许依赖仅限 stdlib、Pydantic、
contracts 和本模块；公开重导出、Protocol 与通用模块边界检查保留。

在项目现有 `.venv` 执行的最终结果：

| 实际命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest src/engineering_rag/modules/query/tests -q` | 81 passed，2.34 秒；其中 80 个新增 Understanding 用例 |
| `.venv/bin/python -m pytest tests/contracts -q` | 175 passed，1.44 秒 |
| `.venv/bin/python -m pytest tests/architecture -q` | 9 passed，1.53 秒 |
| `.venv/bin/python -m pytest -q -rs` | 577 passed、24 skipped，11.22 秒；正常收集执行，无失败 |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 326 files already formatted |
| `git diff --check` | 通过，无输出 |

其余模块也分别执行 `.venv/bin/python -m pytest src/engineering_rag/modules/<模块>/tests -q`：
Parser 170、Chunking 36、Keyword 30、Vector 9、Hybrid 34、Generation 1，均 passed。
Generation 的一项仍只是 Protocol 骨架测试，不是生成业务验收。

完整回归的 24 项 skip 与基线数量相同：原 PDF 审计 1、真实 Elasticsearch 1、
MinerU 真实产物/回放 19、真实 Chunking 1、Embedding smoke 1、Milvus 1，均因相应启用
环境变量、PDF 路径或服务 URI 未配置。本任务不要求或启用这些外部集成；不能计为通过。
没有新增 skip 或降低已有断言，没有使用真实模型，也没有宣称分类准确率。

## 5. 文件清单与范围核对

相对于开始时干净的工作区（HEAD `6372385`），新增 10 个文件、修改 2 个文件：

| 路径 | 类型 / 原因 |
| --- | --- |
| `src/engineering_rag/modules/query/internal/config.py` | 新增；预算与可信部署范围配置 |
| `src/engineering_rag/modules/query/internal/models.py` | 新增；严格输出、候选、证据及审计结果 |
| `src/engineering_rag/modules/query/internal/errors.py` | 新增；单一异常与分类错误码 |
| `src/engineering_rag/modules/query/internal/prompts.py` | 新增；版本化 Understanding 提示 |
| `src/engineering_rag/modules/query/internal/evidence.py` | 新增；原文区间、语义标签、条文格式及标准遗漏保护 |
| `src/engineering_rag/modules/query/internal/scope_validator.py` | 新增；可信目录四态、身份/入库范围/快照核验 |
| `src/engineering_rag/modules/query/internal/filter_merger.py` | 新增；不扩大范围的求交与文档配对 |
| `src/engineering_rag/modules/query/internal/understanding.py` | 新增；注入式理解入口与有界尝试 |
| `src/engineering_rag/modules/query/tests/test_understanding.py` | 新增；80 个离线正反用例 |
| `src/engineering_rag/modules/query/INTERFACE.md` | 修改；同步已实现内部能力与未实现公开能力 |
| `tests/architecture/test_query_dependency_contracts.py` | 修改；历史空目录门槛改为当前阶段可执行边界检查 |
| `docs/task-6.1-query-understanding.md` | 新增；实现选择、实测结果、限制与交付清单 |

已检查 diff：公共 contracts、Query api.py、pyproject.toml、Parser、Chunking、所有检索模块
和 Generation 均无改动。没有 Git 提交；没有开始 Task 6.2。

结论：**Task 6.1 内部实现与离线验收 PASS**；真实模型/生产目录仍未接入，不属于已验证能力。

## 6. 未验证事项与 Task 6.2 前置条件

真实 LLM、生产目录、供应商数据传输政策均未接入；本任务未访问网络，也未声称真实集成
通过。缺少人工意图金标，不报告意图准确率或检索收益。标准名遗漏、复杂否定/指代的可靠性
仍需真实模型与人工样本评估；本地证据规则不能替代语义真实性验证。

Task 6.2 须先由维护者验收本阶段并明确启动，然后消费原 QueryRequest 和内部结果中的
processing_intent、已核验 filters、证据与目录快照；改写不得改变已验证范围。真实模型验收
还需可信注入适配器、模型配置、数据政策和同步入库目录。本次不启动这些后续能力。
