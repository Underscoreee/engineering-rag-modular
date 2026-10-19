# Task 7.1：ContextBuilder + LLM Generation 验收报告

日期：2026-10-19（Asia/Shanghai）。基线 Commit：
`93615eb7f936fe997a33a348b3991f3f44bb59a9`，开始时 Git 工作区干净。

结论：**实现、离线回归、真实 API 示例 Smoke 均 PASS；人工核验真实规范证据验收 PARTIAL**。
维护者明确回复“暂无真实 RetrievalResult，请生成示例文件继续”，因此提供明确虚构的
脱敏示例并执行真实 API，不冒充人工核验真实标准。未提交 Git，未开始 Task 7.2。

## A. 前置条件

重新检查 Task 7.0.1 实际源码：

- 唯一 RetrievalResult 2.0 有严格三态 is_explanation/is_mandatory 与既有 content_type。
  null 保持未知，非法类型/枚举拒绝。
- Elasticsearch 从真实 _source 映射；Milvus OUTPUT_FIELDS 与真实字段一致，严格整数
  mandatory_state 的 -1/0/1 映射 None/False/True，没有 bool(-1)。
- Hybrid 保留已知属性、未知补齐，已知冲突显式报错，不依赖分支顺序。
- QueryResult.evidence→JSON→GenerationRequest.evidence 使用同一公共类型，字段不丢失。
- 前置定向验证：**357 passed（3.11s）**，涵盖三个来源属性、双返回映射、Hybrid、Query、
  Generation 契约和架构。完整基线：**1433 passed、25 skipped（22.51s）**。
- Document Frozen V2.4、Chunk、全部公共契约/Protocol 相对本次基线逐字节未改。

前置条件 PASS，无需修改公共契约。未重新执行已有真实数据库只读测试；本任务不访问
数据库，前置 Task 7.0.1 的真实后端证据仍保留于其原运行目录。

## B. 实现结果

### ContextBuilder

输入是既有 GenerationRequest。私有输出 GenerationContext 包含原问题、整理后的历史、
完整证据数据、请求级 evidence ID 注册表、字符估算、跳过记录和历史省略数。

重校验快照后按 rank 稳定排序；相同 rank 保留原顺序，不比较跨来源 score。
同 chunk_id 去重，但除 rank/score/backend/index 外的内容、身份、来源属性不同即
evidence_conflict。不同 chunk_id 不合并；各请求独立注册表，ID E1/E2… 只允许引用实际
纳入的输入对象。原始请求不修改，未知属性不补猜。

现有 token 计数器只在 Chunking 私有目录，没有可合法跨模块复用的共享计数器。因此使用
序列化应用 input + output_schema 的保守字符预算，明确不是 token 数或完整模型窗口。
默认 48000 字符，先保留系统规则与当前问题，再尝试高排名完整证据；过长整块跳过并记因，
继续尝试后续较小完整块。公式、条件、符号、表头/数据/表注及条文原样保留，不截断或补写。
剩余预算保留最近完整历史后缀并恢复原顺序（默认 8 轮、4000 字符）。

没有有效完整证据时返回固定 insufficient_evidence，不调用 LLM。无法容纳系统/当前问题时
报 context_budget，输入非法时显式拒绝。输出 token 上限沿用 StructuredLLMConfig。

### Prompt 与 StructuredLLMClient

固定工程规范规则与 question/history/evidence 分离，嵌套文本不提升为系统指令。
要求保留数值、单位、否定条件和适用范围，区分正文/条文说明、强制性 true/false/null，
不编造标准/版本/条文/公式/页码，不凭常识判断版本效力或优先级。
历史回答、Expansion、HyDE 不自动作为证据。

私有 GenerationOutput 仅含 answer、evidence_ids、grounding_status、limitations，
extra=forbid；正式调用 response.validate_output 绑定 request/model/revision/Schema 并
严格校验，之后执行 ID、状态与长度检查。业务模块只依赖 contracts/本模块，不实例化 SDK。

既有通用适配器固定文本“No … answer generation …”会禁止本阶段目标，最小修改为
“No Markdown fences or text outside the JSON object.”，允许 JSON answer 字段，仍禁止
JSON 外部散文。HTTP、参数、输出解析、重试、Query 均未修改；实际序列化离线测试和现有
64 项适配器测试通过。此必要措辞调整已记录 [ADR-GEN-001](adr-generation-context.md)。

### 服务、状态与最小引用

公开入口：

```python
from engineering_rag.modules.generation.api import create_generation_service

# settings 为模块 GenerationSettings，llm 为既有 StructuredLLMClient 注入实例。
# service = create_generation_service(llm=llm, settings=settings)
# answer = service.generate(request)  # GenerationRequest -> AnswerResult
```

GenerationSettings 复用 StructuredLLMConfig，provider 来自组合入口现有配置，不新建供应商
配置系统。请求的既有 GenerationConfig 只覆盖对应 config_id/temperature/max_output_tokens。

按模型使用 ID 列表首次出现顺序去重，只从本次注册表映射现有 Citation 的真实
chunk/document/clause/pages，缺失 clause_id 保留 null，quoted_text=null。
不允许模型自由生成来源身份；未知 ID 不替换、不静默丢弃。最后执行既有
validate_answer_citations。没有伪造引文或新增公共字段。

grounded/partially_grounded 必须有本次有效 ID；insufficient_evidence 不得有已使用 ID。
明显矛盾或非法 ID 报错。模型 grounded 但有 limitations/跳过证据时降为 partially_grounded。
insufficient_evidence 使用固定不足文本，不发布模型无依据的确定结论。
这不是逐句语义蕴含或所有答案事实正确的证明。

超时、连接、结构化 ValueError 按既有类别最多尝试两次；认证、限流、服务端错误、明确的
身份/状态错误不隐式重试。错误保留安全类别，不泄露原始异常，不返回缓存或假答案。
logging 与 service.calls 记录 trace/model、数量、字符估算、耗时、用量和校验状态；
不默认记录问题、证据、答案、密钥。calls 为最近 100 次尝试的线程安全诊断深拷贝。
客户端生命周期由组合入口管理，导入和构造无网络副作用。

## C. 文件变更

| 文件 | 原因 |
| --- | --- |
| modules/generation/api.py | 导出实现、运行配置、错误和工厂；保留原 Protocol/DTO |
| modules/generation/internal/context.py（新增） | 请求级注册表、身份检查、整块预算与历史处理 |
| modules/generation/internal/models.py（新增） | 模块运行配置、私有模型输出、安全错误 |
| modules/generation/internal/prompts.py（新增） | 固定版本的可信应用规则 |
| modules/generation/internal/service.py（新增） | 调用、正式校验、有界重试、最小引用、诊断 |
| modules/generation/INTERFACE.md | 完整调用方式、预算/失败语义、版本与当前限制 |
| modules/generation/tests/helpers.py（新增） | 明确虚构证据和离线 Fake LLM |
| modules/generation/tests/test_context.py（新增） | 90 项上下文/三态/来源/预算测试 |
| modules/generation/tests/test_service.py（新增） | 生成、错误、重试、状态、引用、usage 测试 |
| modules/generation/tests/test_prompt_safety.py（新增） | 实际适配器离线序列化的指令隔离 |
| modules/generation/tests/test_contract.py | 保留 Protocol 测试，增加示例契约往返 |
| infrastructure/llm/internal/adapter.py | 仅澄清一处固定系统措辞，允许结构化 answer |
| infrastructure/llm/INTERFACE.md | 记录上述澄清，不改供应商配置/HTTP |
| tests/architecture/test_generation_boundaries.py（新增） | 生产模块无其他业务/基础设施/数据库导入 |
| examples/generation_request.example.json（新增） | 合法、明确虚构的公开请求示例 |
| scripts/generation_smoke.py（新增） | 显式计费开关、复用配置/适配器、只写新产物 |
| docs/adr-generation-context.md（新增） | 字符预算、最小引用及示例验收边界 |
| docs/architecture-decisions.md、README.md | 同步本阶段能力与入口 |
| 本报告（新增） | 实际结果与剩余事项 |

表内 modules/、infrastructure/ 前缀均相对 src/engineering_rag/。
本次共 20 个新增/修改文件（不含忽略目录中的运行产物）。无无关已有工作区修改被覆盖。

## D. 实际测试结果

使用仓库 `.venv/bin/python`、`.venv/bin/ruff`，普通测试均离线。

| 检查 | 命令（省略 .venv/bin/） | 实际结果 |
| --- | --- | --- |
| 前置来源链路 | 见 00-prerequisites.log | 357 passed |
| 修改前基线 | python -m pytest -q | 1433 passed、25 skipped |
| ContextBuilder | python -m pytest src/engineering_rag/modules/generation/tests/test_context.py -q | 90 passed |
| Generation 独立 | python -m pytest src/engineering_rag/modules/generation/tests -q | 129 passed |
| contracts | python -m pytest tests/contracts -q | 285 passed |
| architecture | python -m pytest tests/architecture -q | 15 passed |
| 完整最终回归 | python -m pytest -q | **1553 passed、25 skipped、0 failed（23.70s）** |
| Parser 独立 | python -m pytest src/engineering_rag/modules/document_parser/tests -q | 170 passed |
| Chunking 独立 | python -m pytest src/engineering_rag/modules/chunking/tests -q | 36 passed |
| Keyword 独立 | python -m pytest src/engineering_rag/modules/keyword_retrieval/tests -q | 112 passed |
| Vector 独立 | python -m pytest src/engineering_rag/modules/vector_retrieval/tests -q | 99 passed |
| Hybrid 独立 | python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q | 62 passed |
| Query 独立 | python -m pytest src/engineering_rag/modules/query/tests -q | 351 passed |
| LLM 适配器 | python -m pytest tests/infrastructure/llm -q | 64 passed |
| Ruff lint | ruff check . | PASS |
| Ruff format | ruff format --check . | PASS |
| Diff 检查 | git diff --check | 退出码 0，无输出 |

普通全量测试的 25 个 skip 仍为既有显式外部环境测试等，未跳过任何新增反例或降低断言。
开发中新增示例测试曾因错误 parents 层级失败（1 failed、128 passed），已改为实际文件位置
向上寻找 AGENTS.md+pyproject.toml 标志，最终通过；没有复制示例或改业务来绕过。

日志：`data/eval/task7_1/runs/validation-20261019/`，包括前置/基线、01～15 分项测试与
scope-audit.json。范围审查确认全部公共 contracts、Parser/Chunking、Query/检索代码不变；
适配器相对 HEAD 恰为一处字符串替换，未改其他生产路径。

### 真实 LLM API Smoke（示例证据，不是人工金标）

按维护者确认的示例方案，实际执行：

```bash
.venv/bin/python -m scripts.generation_smoke --env-file .env \
  --request examples/generation_request.example.json \
  --output-dir data/eval/task7_1/runs/real-example-v1 --allow-real-api
```

**PASS，退出码 0**。既有 provider=deepseek、model_id=deepseek-flash；没有改 .env 或写死
供应商/模型/地址，密钥不进入日志或文件。输入为一条固定虚构演示问题与 1 条示例证据。

- 整体耗时：4.029 秒；Generation 尝试耗时：4.025 秒；实际调用 1 次，无重试。
- 真实 usage：input_tokens=1313、output_tokens=431、total_tokens=1744。
- 响应通过正式本地 Schema 校验、非空答案、合法 E1、最小来源映射与 AnswerResult JSON 往返。
- C1 指向输入 fictional-generation-chunk-1 / fictional-generation-document /
  fictional-generation-clause-1，物理页范围 2～2，没有编造引文。
- 模型报告虚构材料和强制性未知的限制；结果保守为 partially_grounded，不将 null 改为 false。
- model_version=null，未从模型名称猜测版本。未访问检索数据库，也未发送真实规范内容。

产物：

- `data/eval/task7_1/runs/real-example-v1/answer.json`
- `data/eval/task7_1/runs/real-example-v1/report.json`
- `data/eval/task7_1/runs/validation-20261019/16-real-example-smoke.log`

report 明确记录 human_verified_real_evidence=false、semantic_correctness_human_review=NOT RUN。
再次执行必须另指定新输出目录，拒绝覆盖本次产物。

## E. 未完成事项、风险与停止点

- **人工核验真实规范证据 Smoke / 真实工程答案人工评估：NOT RUN**。维护者尚无该证据，
  以获准的虚构示例继续；真实 API 可用不等于规范事实正确性已验收。
- Task 7.2 待做完整 CitationMapper/AnswerValidator：段落引用覆盖、逐句支持、严格引文、
  自由文本条文号/数值/条件匹配及更完整质量评估。本阶段只验证输入身份和页范围。
- 未证明 Prompt 能抵御所有语义注入；测试证明可信规则与数据在传输层分离。调用方必须
  提供可信召回对象，Generation 不能从公共 DTO 判断被冒充为检索结果的 HyDE 文本。
- 字符预算是可解释估算而非模型 tokenizer/上下文窗口硬保证；过长证据整块省略会降低覆盖。
- API 调用与重试可能计费，输出不承诺确定性；没有缓存答案兜底。未提供可信 revision 时
  不宣称模型版本固定。没有本任务失败或新增契约阻塞。
- 完成 Task 7.1 范围后停止；没有检索/数据库变更、没有自动提交或进入 Task 7.2。
