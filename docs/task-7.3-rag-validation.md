# Task 7.3：Generation 独立测试与真实 RAG 验证

日期：2026-10-19；基线 Commit `ef2b4b7070119bbb42d427a5dc77ec5fe990e5c4`，开始时工作区干净。
本文与 `data/eval/task7_3/runs/` 下实际运行日志共同构成交付；不自动提交 Git。

## A. 前置与边界

Task 7.1/7.2 软件前置通过：Generation/契约/架构 593 passed；完整修改前基线
1717 passed、25 skipped（21.50s）。这不是前阶段真实规范人工语义验收。
真实 ES 8.19.0、Milvus、已缓存的 BGE 中文模型可用，.env 的 DeepSeek 真实 API 可用。
Milvus Compose 固定 v2.5.4；此处不把 Compose 标签当成独立运行时版本探测结果。

公共协议/DTO（含 Frozen Document 2.4、Chunk 1.0、RetrievalResult 2.0）没有修改。
未修改 Parser、Chunking、Query、Keyword/Vector、Hybrid 生产算法或 LLM 适配器。
唯一生产逻辑修复：Generation ContextBuilder 也拒绝纯空白 standard_code，避免无可靠标准
身份时进入付费调用。先新增反例，实际 RED 1 failed，再修复为 PASS；日志 `01-boundary-red.log`。
其余此前已覆盖的来源三态、预算、表格/公式、非法 ID、quote、异常和状态规则不重复重写。

## B. 分层与真实配置

- A：Fake LLM/检索替身 + 实际 Query/Hybrid/Generation 模块组成离线测试，不冒充数据库。
- B 正式：NOT AVAILABLE，缺少人工核验的真实正文、说明、数值/公式 RetrievalResult 与核验记录。
  维护者明确表示暂无金标并授权生成示例；没有伪造真实标准内容或 verified 标签。
- B 补充：复用 `scripts.generation_smoke` 与既有虚构 GenerationRequest，真实 DeepSeek
  `deepseek-flash` 调用 PASS，4.494647s；输入 1712、输出 670、总计 2382 tokens。
  引用合法、AnswerResult 有效，状态 partially_grounded；不能替代正式 B 或语义质量验收。
- C：实际从 QueryRequest 调用 Query.execute 一次，真实 Query/Hybrid/ES/Milvus，
  再将 QueryResult.evidence 原样送入 Generation。没有预制检索结果，没有绕过 Context/Mapper/Validator。
  没有新建公共编排 API，只增加测试组合入口。

### 隔离与来源

维护者明确批准仅创建 `test_task73_` 新隔离目标。实际 ES 索引、Milvus Collection 均为
`test_task73_20261019_a2`，创建前检查两者不存在；运行后保留，无删除或清理操作。
新目标各入库 1305/1305、failures=[]。ES 23.083847s，向量批量编码/入库 205.289384s。
复用真实 ChunkBatch：
`data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json`，SHA-256
`49daa3d96006149b62b5887f72082d27a23e37ce15aeb50349807680d800f162`。

文档 `doc-dab4ba42814d5a878df723d32b346337`，GB 50010-2010，2015年版。
BGE `BAAI/bge-small-zh-v1.5`，revision `7999e1d3359715c523056ef9478215996d62a620`，
512 维、归一化、COSINE；未下载模型。完整双库 inventory 核对全部 ID/content/metadata、模型
兼容性与 corpus hash，未独立重算所有旧向量值，不能额外声称做了向量值全量比对。
Milvus Strong count 与完整 query iterator 为 1305；即时物理行统计的 0 不误判为逻辑空库。

原知识库仅只读预检：ES `engineering-rag-gb50010-v6`、Milvus
`engineering_rag_gb50010_full_v6`，均为 1305，未向其调用 index/delete。
检索来源与实际 Prompt 逐字段核对，实际 Prompt ID 子集限定最终 Citation；不重新推测上下文。
空证据不得调用 Generation LLM。未知强制性标记仍为 null，不推断标准没有强制性条文。

### 首轮真实 E2E（原配置）

`real-e2e-20261019-a2/report.json`：模型输出上限 2048、超时 30s，8 类候选实际执行，
**5 PASS、3 FAIL、0 跳过、0 未运行**；总耗时 391.160710s（包括模型加载和入库）。
26 次真实 API 尝试，输入 55090、输出 29182、总计 84272 tokens，含失败与重试。

| 用例 | 结果/grounding | 召回/Prompt/引用 | 耗时 s |
| --- | --- | --- | --- |
| exact 精确条文 | PASS / partially_grounded | 3/3/3 | 16.039 |
| standard 指定标准 | PASS / partially_grounded | 3/3/3 | 12.660 |
| clause 指定条号 | FAIL / 无答案 | 3/3/0 | 25.015 |
| formula 公式/条件 | FAIL / 无答案 | 2/2/0 | 29.789 |
| table 表格/表注 | FAIL / 无答案 | 2/2/0 | 29.183 |
| explanation 条文说明 | PASS / partially_grounded | 1/1/1 | 27.035 |
| mandatory 强制性元数据 | PASS / insufficient_evidence | 0/0/0 | 9.177 |
| missing 证据不足 | PASS / insufficient_evidence | 0/0/0 | 9.746 |

上述 caller_filters 是明确的测试输入，不证明 Query 自动推断分类准确；每个用例真实执行双后端，
具体请求、rank/filters/命中、query stages、实际 Prompt IDs 和 Citation 在各 `*.diagnostics.json`。
question/plan 及脱敏 AnswerResult 在受控 data/eval 产物中保存，不默认保存完整 Prompt。

### 输出预算对照

首轮不覆盖、不美化。只读复用同一隔离索引，并重新验证完整 inventory；以进程变量
`ERAG_LLM_MAX_OUTPUT_TOKENS=8192 ERAG_LLM_TIMEOUT_SECONDS=60` 运行 b1 对照，.env 不变。
最终对照结果见下方追加验收记录。

## C. Golden Dataset 与指标边界

实际原金标 `data/evaluation/query/gb50010-v1`：queries=0、qrels=0。
本次示例 `examples/generation_evaluation/task73-review`：8 条 draft、0 qrels、0 review，
沿用 Task 6.5 格式与 load_dataset/评估器；manifest 固定真实语料/来源哈希。
既有示例 `examples/query_evaluation/v1` 为虚构演示，也不是人工金标。
实际运行旧评估器 validate_only，两目录都为 DRAFT_VALIDATED、formal_dataset_ready=false、
official_quality_metrics=null；原空集有 empty_dataset，示例有逐条 unverified_query/missing_qrels。
未新建第二套 Ranking 评估器，没有将自动相关性或模型自评用作标签。

正式 Recall@k、MRR@k、nDCG@k、事实主张覆盖率、正文/说明人工分类准确率、
工程答案质量均为 **NOT AVAILABLE**。8 个类别均缺人工标签及参考答案。
自动引用指标只描述成功输出的机器来源一致性：首轮 7/7 引用授权、7/7 身份匹配、
7/7 Prompt 来源字段透传，原始 quote 子串 3/3；三个失败用例单独计数，不从成功率分母消失。
公共 Citation 没有独立标准代码/三态字段，标准与属性通过 chunk ID 与原输入绑定核对，
没有谎称 Citation JSON 新增这些字段。原文子串存在不等于条件、法律效力或工程语义正确。

## D. 失败分类与复核

- B/Generation 内部：纯空白 standard_code 未拒绝，RED 复现并定向修复，未修改公共 Schema。
- A/测试入口：首次 a1 的敏感值过滤错误地把 MAX_OUTPUT_TOKENS/TOKEN_PARAMETER 配置当
  凭证，写库前失败；02-real-e2e.log 保留，a1 无索引写入。修正为凭证字段后缀匹配，
  仍复用既有防泄漏 writer；不输出 secret 值。新入口也拒绝覆盖旧报告、符号链接目录。
- D/模型配置：a2 的 clause、formula、table 各两次 Generation 均 truncated_output，
  API 实际输出 2047/2048 附近，2048 预算不足；返回异常，没有未经验证正常答案。
  不修改检索/引用算法；b1 仅改变显式进程配置，不宣称必然成功。
- E/数据：人工金标、人工真实规范 B 类证据、参考答案和强制性权威正例均缺失。
- C/F/G：没有擅自修 Query/Hybrid/公共契约；其他实际异常以 run diagnostics 为准。

三个首轮失败的完整问题、预期证据缺口、retrieved_chunk_ids、included_chunk_ids、
空引用/空 grounding_status、generation 失败阶段、error_code 与调用 usage 分别在
`clause.diagnostics.json`、`formula.diagnostics.json`、`table.diagnostics.json`；没有伪造预期答案。
建议优先复核输出预算/模型策略及真实返回，再补人工金标；不是关闭引用校验或截断 Chunk。

## E. 文件与复现

- `generation/internal/context.py`：唯一生产变更，纯空白代码输入保护。
- `generation/tests/test_task73_gaps.py`：RED/回归保护，拒绝发生付费模型调用。
- `scripts/_rag_validation.py`：观测实际 Prompt，检查原始来源/引用、失败阶段、非金标结构指标。
- `scripts/rag_e2e_smoke.py`：公开工厂组合真实链路，严格新目标/只读复用两模式与日志，不删除数据。
- `tests/integration/test_rag_e2e_workflow.py`：离线公共链路、原始公式/表格、说明、空证据、异常、
  Prompt 来源篡改、bool/int 区分、旧目标与历史输出保护、reuse 全 inventory gate。
- `examples/generation_evaluation/task73-review/`：manifest、8 条 draft queries、空 qrels/review、
  人工复核说明。不是新格式，不修改原 Golden Dataset。
- Generation `INTERFACE.md`、本文：契约边界、真实测试命令与诚实结果。

运行命令见 Generation INTERFACE 的 Task 7.3 组合验证段；精确本次目标为
`test_task73_20261019_a2`，首轮目录 `real-e2e-20261019-a2`，只读对照目录
`real-e2e-20261019-b1`。两轮目录不同；再次 create 同名目标会失败，reuse 绝不调用 index。
所有日志：`data/eval/task7_3/runs/validation-20261019/`，实际答案与逐用例诊断位于两轮目录。
正式人工复核要求及缺失项见示例 annotation_guidelines.md。

## F. 回归检查

按任务顺序实际执行 `.venv/bin/python -m pytest <路径> -q`：

| 路径 | 结果 |
| --- | --- |
| src/engineering_rag/modules/generation/tests | 293 passed |
| src/engineering_rag/modules/query/tests | 351 passed |
| src/engineering_rag/modules/hybrid_retrieval/tests | 62 passed |
| src/engineering_rag/modules/keyword_retrieval/tests | 112 passed |
| src/engineering_rag/modules/vector_retrieval/tests | 99 passed |
| tests/contracts | 285 passed |
| tests/architecture | 16 passed |

最终 `tests/integration/test_rag_e2e_workflow.py`：19 passed（0.50s）；
Parser 独立 170 passed（10.41s），Chunking 独立 36 passed（0.39s）。
最终 `python -m pytest -q -rs`：**1737 passed、25 skipped、0 failed（22.72s）**。
此前中间全量 1733 passed/25 skipped（72.63s），后补充2个 Prompt 类型反例及2个隔离写保护反例，
数量增加到最终1737，不混用两次结果。Ruff lint PASS；format **418 files already formatted**；
`git diff --check` 退出码0，无输出。日志10～25记录命令结果，21含全部跳过原因。
25 skips 与基线相同：Parser原PDF/真实回放、Chunking真实回放及独立DB/模型环境门槛等。
普通 pytest 没有自动加载 .env；真实 ES/Milvus/LLM 已由独立脚本显式执行，不能混为同一测试数。
不跳过新增反例，不修改原有断言，不把普通 pytest 中未启动的外部集成测试当真实后端验证。

## 最终追加验收记录

### b1：显式8192输出token / 60秒，只读对照

`real-e2e-20261019-b1/report.json` 实际 **PASS、8/8、0失败、0跳过、0未运行**，
总耗时 **169.738573s**（包括快照核查/模型准备，不重新入库）。22次真实 API 调用，
输入 **44164**、输出 **32669**、总计 **76833 tokens**。

| 用例 | 结果/grounding | 召回/Prompt/引用 | 耗时 s |
| --- | --- | --- | --- |
| exact | PASS / partially_grounded | 3/3/3 | 15.616 |
| standard | PASS / partially_grounded | 3/3/3 | 17.590 |
| clause | PASS / partially_grounded | 3/3/3 | 30.336 |
| formula | PASS / partially_grounded | 2/2/2 | 33.186 |
| table | PASS / partially_grounded | 2/2/2 | 33.427 |
| explanation | PASS / partially_grounded | 1/1/1 | 11.189 |
| mandatory | PASS / insufficient_evidence | 0/0/0 | 7.801 |
| missing | PASS / insufficient_evidence | 0/0/0 | 9.838 |

本轮实际 query_understanding/query_rewrite 及六次 Generation 走真实 API；
八个问题均走 acquisition，真实 Expansion/HyDE 未触发，不据此宣称其真实效果已验收。
两次空证据结果没有调用 Generation LLM。六个非空结果都保守部分依据，未伪称已证明全部结论。
实际引用授权 **14/14**、来源身份匹配 **14/14**、Prompt原始来源行透传 **14/14**、
原始引文子串 **9/9**；其余 Citation 没有 quote 时不填造引文，不计入quote分母。
这些都是程序结构/来源一致性，不是人工相关性、事实覆盖或工程答案正确率。

前后只读预检 `environment-preflight-v1` 与 `environment-postcheck-v1`：
原 ES index UUID、Milvus collection ID、两侧全部1305条身份/内容/元数据摘要均一致，
原 ChunkBatch SHA-256 一致。两个脚本预检退出码2是既有脚本对 preflight-only 的整体
PARTIAL/端到端NOT RUN语义；backend、inventory及两个搜索探测本身均 PASS，不误报基础设施失败。
原 Document/PDF 哈希沿用既有数据集manifest，本次未重新推理PDF，也没有把这些声明当成人工核验。

### 最终分层建议

| 项目 | 结论 |
| --- | --- |
| Generation离线与公共契约/架构 | PASS |
| 真实LLM + 虚构示例（补充Smoke） | PASS，不是正式B |
| 人工核验真实规范B类 | NOT AVAILABLE，核验数据缺失 |
| 真实Keyword / Vector / Hybrid | PASS，b1真实双后端8次检索 |
| 真实完整RAG程序链路 | PASS（b1 8/8；a2原预算5/8，历史失败保留） |
| Golden检索指标/答案人工语义质量 | NOT AVAILABLE |
| 总体验收建议 | **PARTIAL**：软件/来源链路通过，人工工程语义质量未验收 |

产物定位：两轮各有8个 `*.diagnostics.json`，成功案例各有 `*.answer.json`，
scope/report保存隔离边界、真实配置/快照/汇总；数据保护规则下不默认落盘完整Prompt。
最初a1仅有空产物目录和失败终端日志，无索引写入、无成功API声明。
无公共Schema变更，无自动提交，无数据删除，测试隔离目标留给维护者后续决定。

## G. 未完成事项

总体不能作为人工规范语义质量的全 PASS：需人工提供经核验的正文、说明、数值/公式三类
RetrievalResult，复核八类 queries/qrels、答案要点和权威强制性证据；再经正式评估门槛。
自动来源授权不等于逐句蕴含、全文事实覆盖、标准效力或专业工程结论正确。
本次停在 Task 7.3，不自动提交，不进入下一阶段。
