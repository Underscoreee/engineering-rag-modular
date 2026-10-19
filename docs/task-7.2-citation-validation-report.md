# Task 7.2：CitationMapper + AnswerValidator 验收报告

日期：2026-10-19（Asia/Shanghai）。基线 Commit：
`7ae773226ade458f1c15395dcffab9de3862f03c`。开始时 Git 工作区干净。

结论：**本次引用映射、字面引文、结构与状态校验实现 PASS；人工真实规范语义质量验收仍为 PARTIAL**。
未修改公共 Schema/版本/API，未提交 Git，未进入 Task 7.3。

## A. 前置条件与真实契约

重新检查已提交的 Task 7.1：有正式私有 GenerationOutput、StructuredLLMResponse.validate_output、
请求级 GenerationContext.registry 与完整生成流程。registry 仅包含实际进入 Prompt 的证据，
可回到原始 RetrievalResult 快照，没有从知识库全量范围补源。

Generation/契约/架构前置验证 **429 passed（7.19s）**；修改前完整基线
**1553 passed、25 skipped（53.11s）**，因此软件前置 PASS。维护者发起本任务作为继续开发授权；
没有把前阶段机器测试或真实 API 示例视为人工规范质量验收。Task 7.1 既有真实人工证据缺口未变。

公共 Citation 仍只有 citation_id、evidence_chunk_id、document_id、可空 clause_id、必填
page_start/page_end、可空 quoted_text；不含标准名称/代码、条文编号、来源三态等新增字段。
AnswerResult 仍含 schema_version、answer、citations、grounding_status、model、warnings。
复用既有 GroundingStatus 与 GenerationError，不创建公共同义 DTO/Enum。

检查 Evaluation：现有评估能力面向 Query/检索，不存在已实现的 Generation 逐句语义评估；
本次不把检索指标当作答案质量指标，也不修改评估模块。

## B. CitationMapper

内部入口：

```python
# CitationMapper.map(output: GenerationOutput, context: GenerationContext) -> CitationMapping
```

CitationMapping 仅持有有序 evidence_ids、公共 Citation 元组和原 Context 的对象绑定。
没有第二套证据注册表，也没有请求之间的可变全局状态。

### 授权、来源与去重

- 只接受当前注册表中的精确 ID；当前召回但被预算省略的 Chunk 不可引用。
- 与 Prompt 中的来源行逐字段核对，验证标准身份、版本、文档、条文、内容、页码、
  is_explanation/is_mandatory/content_type 及其未知值，检测对象被改、同 Chunk 多来源、
  多出未送入 Prompt 的记录等问题；bool 与 0/1 不混为相同类型。
- 模型只能提议 evidence ID 和 quote，不允许自由提交标准代码、条文号、页码、强制性等来源
  字段；额外字段由正式私有 Schema 拒绝，而非覆盖真实元数据。
- 顺序为模型 evidence_ids 列表首次出现顺序；相同 ID 去重，不合并不同 Chunk。
  仅答案级列表，不能声称已验证自由正文中的每次引用位置。
- C1/C2… 的 chunk/document/clause/pages 只从实际对象填充。可空身份保持 null；
  必填字段缺失/空白失败，不猜来源。页范围保持原始完整范围，不无依据缩窄到某页。
- 标准与三态属性仍保存在输入和同一私有 Context；现有公共 Citation 不承载这些独立字段，
  下游可按 evidence_chunk_id 关联本次输入，不能宣称它们已新增进 Citation JSON。

E1 是请求内别名而不是全球唯一 ID。跨请求复用 CitationMapping 会因 Context 对象不一致
报 citation_scope；模型响应还须通过原 validate_output 的 request_id 绑定，不能仅凭同名 E1
接受另一请求的响应。

### 原文引文规则

私有 GenerationOutput 新增可选 quotes（默认 []），EvidenceQuote 仅含 evidence_id/quoted_text。
公共模型无变更，旧模型输出不含 quotes 仍可读；没有 quote 时 public quoted_text=null。

- 首先按 content 实际字符串检查子串。
- 唯一匹配规范化：连续 ASCII 空格、tab、CR/LF 折叠成一个空格，去掉首尾同类排版空白。
  不删除词边界，不把 `1 2` 当成 `12`。
- 数字、正负号、LaTeX 命令/转义位置增加边界保护，避免 `0.1` 引用 `0.10` 等截断匹配。
- 不改数字、单位、Unicode/比较符号或 LaTeX，不做数学等价、模糊数值/语义相似度匹配。
- Formula/Table 的 quote 必须符合 Chunk.content 的实际存储形式。JSON 字符串不自动解码
  为另一个视图，LaTeX 使用已存转义形式。无法匹配就拒绝，不重写引文以求通过。
- 引文 ID 必须同时在当前上下文与已使用 evidence_ids；孤立 quote 明确失败。
- 同 ID 相同 quote 去重，不同 quote 报冲突，不拼接多个片段冒充连续原文。
- 最终 quoted_text 保留原提议，AnswerValidator 再次验证原文，不能仅相信引用 ID。

匹配证明的是字面存在性，不等于摘取片段保留了全部前置条件、否定或语义。

## C. AnswerValidator 与服务集成

内部入口：

```python
# AnswerValidator(max_answer_chars=...).validate(
#     answer, context=context, mapping=mapping, limitations=...
# ) -> AnswerResult
```

严格 Pydantic 重校验当前 AnswerResult/Citation，拒绝空白答案、额外字段、非法版本、
页码字符串/bool、缺少必填来源等；再核验原请求映射、完整来源字段、重复/冲突引用及 quote。
不会因 citation_id 存在就放行。返回新结果，不修改输入，不静默清理错误引用。

状态政策：

- grounded/partially_grounded 必须有真实授权引用。
- 有效 ID 或局部引文都不能证明整份答案充分支持。只有整份答案等于单一已引用 content 的
  **完整文本**（容许规定的空白差异）、且没有 limitations/省略证据时，才保留 grounded。
- 一般改写、总结或已知有限制的回答保守降为 partially_grounded，保留限制说明。
- 即使完整复制，也加 warning：未证明逐句事实主张、相关性、工程适用性或法律效力。
- insufficient_evidence 仅允许既有固定安全文本及空引用，不发布模型记忆中的确定规范结论。
  空证据分支仍不调用模型，并且同样经过 Mapper/Validator；本地固定文本不受极小模型输出
  字符预算阻止，保持 Task 7.1 原行为。

现有服务仅作必要编排调整：ContextBuilder → 原 LLM/validate_output → CitationMapper →
AnswerValidator → AnswerResult。删除 service 中重复的旧映射/状态检查。模型生成与既有
有界重试策略不重写；来源/引用/引文的 GenerationError 不重试、不重新检索、不返回假答案。
可选 quotes 的长度计入原 max_answer_chars。Prompt 内部版本升到 engineering-generation-1.1。

新增安全错误码包括 invalid_registry、source_metadata_conflict、orphan_quote、quote_conflict、
quote_mismatch、citation_scope、citation_conflict、invalid_answer；继续复用 unknown_evidence_id、
evidence_conflict、citation_mapping、grounding_conflict、output_budget 等。默认日志无原始问题、
证据或模型正文；错误只有安全码，仍记录现有 trace/usage/耗时/状态。

## D. 实际测试结果

使用 `.venv/bin/python` 和 `.venv/bin/ruff`。普通测试全部离线，Fake LLM 只验证业务编排，
不冒充真实模型/数据库。最终执行结果：

| 检查 | 命令（省略 .venv/bin/） | 结果 |
| --- | --- | --- |
| CitationMapper | python -m pytest src/engineering_rag/modules/generation/tests/test_citation_mapper.py -q | 112 passed |
| AnswerValidator | python -m pytest src/engineering_rag/modules/generation/tests/test_answer_validator.py -q | 38 passed |
| Generation 独立 | python -m pytest src/engineering_rag/modules/generation/tests -q | 292 passed |
| contracts | python -m pytest tests/contracts -q | 285 passed |
| architecture | python -m pytest tests/architecture -q | 16 passed |
| 完整最终回归 | python -m pytest -q | **1717 passed、25 skipped、0 failed（20.80s）** |
| Parser 独立 | python -m pytest src/engineering_rag/modules/document_parser/tests -q | 170 passed |
| Chunking 独立 | python -m pytest src/engineering_rag/modules/chunking/tests -q | 36 passed |
| Keyword 独立 | python -m pytest src/engineering_rag/modules/keyword_retrieval/tests -q | 112 passed |
| Vector 独立 | python -m pytest src/engineering_rag/modules/vector_retrieval/tests -q | 99 passed |
| Hybrid 独立 | python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q | 62 passed |
| Query 独立 | python -m pytest src/engineering_rag/modules/query/tests -q | 351 passed |
| LLM 适配器 | python -m pytest tests/infrastructure/llm -q | 64 passed |
| Ruff lint / format | ruff check . / ruff format --check . | 均 PASS |
| diff | git diff --check | 退出码 0，无输出 |

日志目录：`data/eval/task7_2/runs/validation-20261019/`（前置/基线、01～18 与 scope-audit.json）。
25 个 skip 保持基线的显式外部环境测试等，未跳过新增反例或放宽来源/引文断言。

开发中真实复现并修复：普通 contains 错收 `0.1`/转义片段（2 failed），以及局部子串
“应施加荷载”错误保留 grounded（1 failed，见 grounding-substring-red.log）。Task 7.1 的
一个正常改写测试仍期望 grounded，集成时实际失败；按新保守政策改为 partially_grounded，
并增加必须存在未验证支持 warning 的断言，不删除原来源映射/usage/不变性检查。

### 真实 API 示例 Smoke

复用既有脚本和已有虚构示例，**没有修改脚本、.env 或标准语料**：

```bash
.venv/bin/python -m scripts.generation_smoke --env-file .env \
  --request examples/generation_request.example.json \
  --output-dir data/eval/task7_2/runs/real-example-v1 --allow-real-api
```

实际 **PASS、退出码 0**，provider=deepseek，model_id=deepseek-flash，可信版本未提供则为 null。
一次真实调用，无重试，整体约 **1.504 秒**（生成阶段约 1.499 秒）；usage 为输入 **1712**、
输出 **200**、总计 **1912 tokens**。没有输出 API Key，没有访问数据库。

模型返回 C1 对应输入 E1，实际 quoted_text 为“检查间隔不应超过7天；本条不适用于水下构件。”，
确实是输入 content 的原始子串，无需规范化。来源为输入的 fictional-generation-chunk-1 /
fictional-generation-document / fictional-generation-clause-1，物理页 2～2；没有伪造页码。
答案保守为 partially_grounded，保留虚构材料和强制性未判定限制。

产物：

- `data/eval/task7_2/runs/real-example-v1/answer.json`
- 同目录 `report.json`、`quotation-check.json`（Schema/身份/JSON 往返/字面引文复查）
- `data/eval/task7_2/runs/validation-20261019/18-real-smoke.log`

真实调用只验证有效返回链路；无效 ID/引文的拒绝证明来自确定性离线反例，不冒充真实模型
恶意输出实验。report 明确 human_verified_real_evidence=false、语义人工核验 NOT RUN。
本次仍使用维护者此前授权的明确虚构示例，不把它提升为真实国家标准金标。

## 文件清单与范围证明

共 15 个新增/修改文件，生产代码全部在 Generation 内：

- 新增 internal/citation_mapper.py、internal/answer_validator.py。
- 更新 internal/context.py（共享原字段投射）、internal/models.py（私有可选 quotes/安全文本）、
  internal/prompts.py、internal/service.py。
- 新增 tests/test_citation_mapper.py、tests/test_answer_validator.py、tests/test_citation_integration.py；
  更新 tests/test_service.py。以上路径均相对 src/engineering_rag/modules/generation/。
- 更新 Generation/INTERFACE.md、tests/architecture/test_generation_boundaries.py。
- 新增 docs/adr-generation-citation-validation.md、本报告；更新 docs/architecture-decisions.md。

scope-audit.json 逐字节对照 HEAD，确认全部公共 contracts、Generation api.py、Parser、Chunking、
Query/Keyword/Vector/Hybrid、基础设施代码不变。没有新依赖、数据库写入或额外业务模块实现。

## E. 未完成事项与限制

- 当前任务没有必须修改公共契约的阻塞。Citation 不含独立标准/条文号/三态字段，这是既有
  表达边界；当前可通过本次输入按 chunk 身份追踪，若未来要在 Citation 单独承载需另行审批。
- 没有段落/claim 级公共引用字段，不能证明每个独立主张受支持；自由答案中的标准名、
  条文号、数值、单位、适用条件不具备通用事实核验。结构化来源字段拒绝/比对不等于全文语义校验。
- 引文检查证明字面存在，不保证摘录没有语境歧义，也不证明源解析准确、条文法律效力或规范版本优先级。
  JSON/LaTeX 表示与原字符串不同会保守拒绝，可能产生可解释的假阴性，不以模糊匹配掩盖。
- 人工核验真实规范证据与工程答案质量评估 **NOT RUN / PARTIAL**，不是 API 配置阻塞。
  现有真实 API 示例成功不能替代该人工工作或正式 Golden Dataset。
- 不保证抵御所有提示注入；模型响应绑定与上下文/数据隔离仍依赖既有正确注入客户端。
  不接受跨请求映射，不从整个知识库或模型记忆补证据。
- 没有自动提交，完成后停止，等待维护者审查；未进入 Task 7.3。
