# Task 6.2：Query Rewrite 实现、内部决策与验收

日期：2026-10-18。只交付 Query 内部 Rewrite；不实现 Expansion、HyDE、Planning、检索或
QueryService.plan/execute，不新增真实模型适配器或网络调用，不修改任何公共契约。

## 1. 开发前核查

工作区初始干净，HEAD 为 `dbf5e7a`。完整基线：`.venv/bin/python -m pytest -q` 实际为
**577 passed、24 skipped，8.13 秒**，Parser 路径问题未再阻塞收集。

实际代码确认：Task 6.1 的 `QueryUnderstanding.understand(QueryRequest)` 返回严格的私有
`UnderstandingResult`，包含两类处理意图、filters、目录响应和候选证据/审计信息，足以供本阶段
消费；Task 6.2 不复制此类型，也不调用 Understanding 或目录。StructuredLLMResponse 的
validate_output 要求请求 ID、模型/显式 revision 绑定及应用模型生成的 Schema，已实际复用。
Query 2.0、Document Frozen 2.4 及检索/Chunk 契约均保持原样。

发现的历史设计差异：Task 6.0 数据流/路线曾建议“失败回退原问题”，而本次明确授权任务要求
纠正后仍失败必须抛异常。**本阶段按本次任务书执行，不提供静默回退**；历史建议保留为历史，
当前 INTERFACE 与本报告明确实际行为。

## 2. 真实入口与数据流

```python
from engineering_rag.modules.query.internal.rewrite import QueryRewrite
from engineering_rag.modules.query.internal.rewrite_models import RewriteConfig

# 接口示例：llm、llm_config 为组合层注入；无默认真实供应商客户端。
rewriter = QueryRewrite(llm=llm, config=RewriteConfig(llm=llm_config))
result = rewriter.rewrite(request, understanding_result)
```

`rewrite(request: QueryRequest, understanding: UnderstandingResult) -> RewriteResult` 只在 Query
内部使用。跨模块公开 API/Protocol 没有变化。步骤如下：

1. 深拷贝并重验输入；检查问题/历史预算，不截断原问题。
2. 检查调用方原 filters 未被 Understanding 扩大、布尔值未被修改，采用证据属于当前问题且
   仍对应采用的 filters；检查明显标准代码/版次/条文冲突。只做输入一致性，不重新验证目录事实。
3. 从原问题和已存在的验证记录中建立保护清单，发起 stage=query_rewrite 的结构化调用。
4. response.validate_output 校验绑定与私有 RewriteOutput；检查主查询预算。
5. 校验有序保护项及局部编辑证明，再独立审查同义词。
6. 返回原问题、单一主查询、可信同义词、新 filters 深拷贝及私有审计结果。

RewriteOutput 只允许 rewritten_query 和 keyword_synonyms，extra=forbid、严格类型；未知
字段、缺失、空白主查询、非法类型都失败。输入不包含未验证的模型答案；纠正只传受控错误码，
不回灌完整异常或未验证输出。获取性和探索性都只进行同一基础阶段。

已只读核查 Keyword 的 build_search_query：接收普通文本，内部转 multi_match。因此本次
不提前组合 keyword_query、不生成 DSL；未来 Planning 决定怎样使用主查询与同义词。

## 3. ADR-Q-002：保守、可证明的局部改写

- 状态：本任务内部实现决策，不改变 ADR-Q-001 的公共契约。
- 原因：仅验证数字/编号集合无法检测“不应 A、应 B”中的对象交换，也无法证明新术语等价。
  本任务禁止新增通用 NLP、真实模型判别器或生产术语目录，因此不能假装完整语义验证已解决。
- 选择：模型负责提出语言规范化，应用要求**全部技术保护序列不变 + 原文逐字复制/审核局部
  规则的单调对齐证明**。无法证明的自由重排、技术对象替换、答案或新参数整体拒绝。

保护包含：标准代码及《名称》/版次/修订、条文/公式/表/图/附录编号、精确数字与常用中英文
单位、LaTeX/拉丁变量/希腊字母/上下标及 Unicode 数学符号、否定/规范强度/数量限制/
条件/比较/包含/排除/因果/先后词。已核验记录中出现在原问题的名称、别名、版次、修订等
也作为保护字面量；未出现的目录元数据不会被强行插入主查询。所有 filters 原样隔离传递，
不允许模型生成新 filters，修订信息继续由已验证的文档身份约束。

对齐仅有两种边：复制同一字符；应用 caller-reviewed LanguageRule。每条规则有 source、target、
prefix/suffix/anywhere 位置及 evidence_id；修改记录是原文 [start,end) 字符范围与替换内容。
原文索引每步严格前进，状态数量有界，无递归模型循环；保护校验不能被规则配置覆盖。
默认规则仅含少量普通口语/错字/问号风格，例如“咋算→如何计算”“请间→请问”，不猜测专业
概念或标准年份。策略指纹包含规则、词表、同义词预算及保护规则版本，便于复核同一策略。

代价：会拒绝许多人工看来正确的自由改写，某些词面保护也可能过度保守。维护者可在人工
审核后注入更多局部规则，但不可接受模型自己声称等价的规则。这是明确的安全/覆盖率取舍，
不是声称 regex 或规则表已完成通用工程语义理解。没有配置可验证的修正时可保持原文，前提
是合法模型响应明确如此且全部校验通过；捕获错误后直接返原问题不属于成功路径。

### 同义词的信任边界

默认 equivalent_terms 为空，绝不臆造同义词。可注入 `EquivalentTerm(term, equivalent,
evidence_id)` 表示维护者已核验的上下文等价关系。仅接受精确匹配且 term 在当前问题中出现的
候选，拉丁缩写须符合标识符边界，不能从另一变量内部截取。丢弃空白、重复、已存在、未审核、
过长、超数量及含编号/数值/答案/约束的候选，并记录 reason；同义词问题不掩盖不安全主查询。

“有限元方法/有限元法”仅以带审查身份的离线夹具测试此机制，不表示已部署权威术语库。
上下位关系、相关术语不能靠 LLM 置信度进入输出。注入者必须保证等价词适用条件和真实性；
如果人为把“抗震等级/抗震设防类别”错误配置成等价，本机制没有额外事实来源可自动纠正。
这一责任与局限公开记录，不把“提供 evidence_id”本身说成权威证据核验。

## 4. 配置、异常、观测与副作用

默认限制：问题/主查询各 8000 字符、历史 8 条/16000 字符、应用同义词 4 个/每个 64 字符；
模型原始候选最多 16 个，规则最多 64 条、等价关系最多 128 条；对齐最多 50000 状态。
max_attempts 为严格整数 1～2；结构化校验、安全纠正与超时/连接重试共享，不叠加。
供应商其他异常不重试；底层客户端必须执行配置超时/token 限制且不得隐藏重试，当前同步
Protocol 不提供强制中断失约客户端的能力。

RewriteError 分为 input_budget、scope_conflict、invalid_output、unsafe_rewrite、model_failure。
真实原因保留 __cause__，失败附已进行的 attempts；正常空同义词不等于主查询失败，主查询
失败绝不变为成功的原问题、空串或默认查询。未知用量保留 null，已知用量沿用响应记录。

INFO 日志仅记录 stage、trace/task/request ID、配置/模型/提示版本、策略指纹、状态、尝试次数、
耗时和可空用量；不安装日志 handler、不记录问题/历史/模型全文，不使用自动记录异常链的日志。
结果和原异常链可能含敏感原文，应受控保存。无导入连接、数据库/文件写入或网络实现；客户端
生命周期与线程安全由注入者负责，服务不持有逐请求可变状态，输入和配置隔离复制。

RewriteResult 含原问题/主查询/同义词、处理意图、filters、保护区间、编辑 lineage、同义词决策、
attempts、trace、版本与指纹，可严格 JSON 往返。固定输入/响应/策略时语义输出和审查顺序稳定；
随机关联 ID、耗时及模型本身不保证逐字确定。

## 5. 测试记录

先写回归用例并实际运行：新入口不存在，出现 1 项预期收集错误。实现后测试覆盖正常口语、
普通错字、冗余表达、保持原文、双处理意图、代码/编号/精度/单位/希腊字母/上下标/LaTeX、
相同 token 集但对象或否定关系交换、无证据专业概念替换、规范强度/条件/因果保护、同义词
信任和去重、输入/输出/对齐预算、请求绑定、非法 Schema、混合故障共享重试、原因保留、
日志、JSON 往返和不修改输入。所有模型回复均为离线替身，不证明真实模型质量。

旧架构测试对 Rewrite 的禁止已实际复现；只为 rewrite.py 中 QueryRewrite.rewrite 方法增加
阶段入口例外，没有全局解除 rewrite 禁止。继续禁止检索、plan/execute、Expansion、HyDE、
外部实现/SDK，并额外检查 Rewrite 文件不得调用 understand/lookup。

项目现有 `.venv` 中最终实际执行结果如下（均 0 failed）：

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest src/engineering_rag/modules/query/tests/test_rewrite.py -q` | 97 passed，2.92 秒 |
| `.venv/bin/python -m pytest src/engineering_rag/modules/query/tests -q` | 178 passed，4.07 秒 |
| `.venv/bin/python -m pytest tests/contracts -q` | 175 passed，1.51 秒 |
| `.venv/bin/python -m pytest tests/architecture -q` | 9 passed，1.69 秒 |
| `.venv/bin/python -m pytest -q -rs` | 674 passed、24 skipped，12.65 秒 |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 333 files already formatted |
| `git diff --check` | 通过，无输出 |

七个模块独立运行能力也已核查；除上表 Query 外，分别执行
`.venv/bin/python -m pytest src/engineering_rag/modules/<模块>/tests -q`：Parser 170、Chunking 36、
Keyword 30、Vector 9、Hybrid 34、Generation 1，均 passed。Generation 一项仅验证已有 Protocol。
contracts 中既有 JSON 示例/Pydantic 校验仍通过，没有修改样例以适应测试。

24 项 skip 与基线相同：原 PDF 审计 1、Elasticsearch 1、MinerU 实产物/回放 19、真实 Chunking 1、
Embedding smoke 1、Milvus 1；缺少相应启用变量、原 PDF 路径或服务连接配置。本次没有新增 skip，
也不将这些可选外部测试记为通过。没有真实 LLM 调用，离线用例不能冒充实际模型质量评估。

结论：**Task 6.2 内部实现及离线验收 PASS**；真实模型与人工语义覆盖率尚未验证。

## 6. 文件与范围

新增：

- `src/engineering_rag/modules/query/internal/rewrite.py`：注入式入口、尝试预算与安全日志。
- `src/engineering_rag/modules/query/internal/rewrite_models.py`：私有模型、配置、规则、结果及错误。
- `src/engineering_rag/modules/query/internal/rewrite_prompt.py`：版本化基础改写提示。
- `src/engineering_rag/modules/query/internal/rewrite_protection.py`：一致性、技术保护与局部对齐。
- `src/engineering_rag/modules/query/internal/rewrite_synonyms.py`：可信等价候选审查。
- `src/engineering_rag/modules/query/tests/test_rewrite.py`：离线正反测试。
- `docs/task-6.2-query-rewrite.md`：本说明、内部 ADR 与验收记录。

修改：Query `INTERFACE.md`、`tests/architecture/test_query_dependency_contracts.py`（本阶段门槛）。
Task 6.1 实现/API、全部公共 contracts、Parser/Chunking/检索/Generation、依赖配置保持不变。
不提交 Git，不进入 Task 6.3。

## 7. 限制与 Task 6.3 前置条件

没有真实 LLM、生产词表、改写人工金标或线上检索实验，不报告改写准确率或召回收益。
当前范围安全依赖对应的成功 Understanding。其现有类型没有原始请求摘要，Rewrite 能检查
明显证据/范围冲突，但不能认证没有证据的两个请求是否同源；组合层必须传递正确对象。
本阶段不为补该追踪能力而擅自修改 Task 6.1 或公共契约。

Task 6.3 须由维护者独立验收并明确启动，之后消费唯一主查询、可信同义词、处理意图和
保持不变的 filters，并继续持有原请求/Understanding；不得把新增条件或生成内容倒灌已验证
范围。真实模型验收还需独立确定适配器、数据政策和审查数据；本任务不启动这些后续能力。
