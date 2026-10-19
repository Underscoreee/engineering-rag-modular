# Task 7.0.1：RetrievalResult 来源元数据验收报告

日期：2026-10-19（Asia/Shanghai）。结论：**PASS（本任务范围）**。
基线 Commit：`a6e46a0e2e4e4f078d7a52f01731762adffc2f97`。
开始时仅有未跟踪的 `docs/task-7-generation-interface-review.md`，保持原内容不变。
未提交 Git，未调用真实 LLM，未实现 Generation，不进入 Task 7.1。

## A. 公共契约与兼容策略

唯一 `RetrievalResult` 版本从 1.0 升至 2.0，新增：

| 字段 | 定义 | 未知语义 |
| --- | --- | --- |
| is_explanation | StrictBool 或 None，默认 None | 未提供，不能推断为正文 |
| is_mandatory | StrictBool 或 None，默认 None | 未判定，不能推断为非强制 |
| content_type | 既有 ChunkContentType 或 None，默认 None | 未提供，不另建枚举 |

严格拒绝布尔字符串/数字，以及非字符串的 content_type（含 bytes 自动转换）；合法 JSON
字符串转换为既有枚举，非法枚举拒绝。无文本、编号、页码或 ID 推断。

新模型通过受控读取桥加载历史显式 1.0 且无新增字段的记录，缺失属性为 null；序列化统一
输出 2.0。1.0 携带新增字段为混合格式错误，未知版本拒绝。显式内存迁移函数为
`migrate_retrieval_result_v1(payload)`，不写文件、不修改输入。历史 examples 与评估 JSON
保持只读，新示例另存 `examples/retrieval.v2.example.json`。

旧 extra-forbid 消费者不能直接接受新字段，须协调升级 contracts；未声称旧消费者兼容。
无已知必须保留的旧版本写出接口，因此没有有损 V1 writer 或第二套生产 DTO。
QueryResult 外层仍 2.0；GenerationRequest、公共 Protocol、全局 SCHEMA_VERSION、Chunk、
Document Frozen 2.4 均不变。详见 [ADR-RR-001](adr-retrieval-result-v2.md)。

## B. 实际存储与映射

Elasticsearch `engineering-rag-gb50010-v6` 的 is_explanation/is_mandatory 为 boolean，
content_type 为 keyword。转换只读取真实 `_source` 同名字段，缺失/null 保留 None，
非法值抛 KeywordResponseError；BM25 `_score`、排序及原有身份字段不变。

Milvus `engineering_rag_gb50010_full_v6` 的 is_explanation 为 BOOL、mandatory_state 为
INT8、content_type 为 VARCHAR，已加入 OUTPUT_FIELDS。严格整数 -1→None、0→False、
1→True；字段缺失为 None；存在但为 null、bool、字符串、浮点或其他整数均抛
VectorResponseError。is_explanation/content_type 缺失或 null 为未知，非法值显式失败。
没有使用 bool(-1)，没有改 COSINE 分数或排序。

两个服务均已存储所需字段，因此 **无需数据库迁移**。未重建索引/Collection，未入库、
删除或清空任何数据。索引/Collection 兼容信息、模型及向量维度均未改变。

## C. 全链路透传验证

```text
Chunk → ES/Milvus → Keyword/Vector RetrievalResult 2.0
      → Hybrid → QueryResult.evidence → JSON → GenerationRequest.evidence
```

Hybrid 在原候选合并器中逐字段处理：相同已知保留；已知+未知保留已知（含 false）；
都未知保留 null；已知冲突抛既有 CandidateConflictError，不按分支顺序覆盖，也不修改输入。

Query 的 execute 已直接传递公共对象，无需改 Query 生产代码。新增测试使用真实 Query、
Hybrid 实现及离线 LLM/检索替身，实际执行 execute 并验证 JSON 与 GenerationRequest。
评估 FixtureRetrieval 是另一处 Chunk→证据构造，同步补三字段，固定分数/排序不变。
它仅是虚构离线夹具，不作为真实后端测试。

真实后端测试确实执行 Keyword、Vector 和 Hybrid 查询，并将实际命中封装为公共
QueryResult/GenerationRequest 往返；**该测试未执行真实 Query 理解/改写，也未执行真实
Query.execute 或 Generation 业务**。实际 Query.execute 的透传由上述离线集成测试验证。

## D. 算法不变性证据

- 对比 HEAD：除 retrieval 契约、两个返回转换器、Hybrid 元数据合并、离线夹具构造外，
  其他已跟踪生产 Python 文件逐字节一致。
- AST 比较确认 Keyword build_search_query/search_chunks/_build_filters、Vector
  search_chunks/build_filter_expression 及其他现有契约定义不变。
- Hybrid fusion.py/service.py 不变；merge_candidates 与原身份校验不变，仅新增元数据
  验证和补齐调用。单元测试覆盖 RRF 与 weighted_normalized 的原分数和排序不变。
- 真实结果对照历史 Task 6.6：相同 Hybrid Top-3 ID、rank、RRF score、Clause 与页码，
  未改变 BM25、Embedding、COSINE、权重、top_k、去重键、Query 策略。
- Document/Chunk/answers/queries/protocols、Parser/Chunking 及索引构建代码均未修改。

机器检查清单：`data/eval/task7_0_1/runs/validation-20261019/algorithm-invariance.json`。

## E. 实际测试

使用仓库 `.venv/bin/python` 与 `.venv/bin/ruff`。修复前完整基线：
**1103 passed，24 skipped（113.31s）**。最初新增定向测试先得到
262 failed、45 passed，实施后该组 307 passed。复核另增加 bytes 类型反例，先实际复现
3 failed、21 passed，再修复；该 RED 日志另存，不作为最终失败。

以下按任务书顺序重新执行，均为最终代码：

| 顺序 / 命令（省略 .venv/bin/ 前缀） | 实际结果 |
| --- | --- |
| python -m pytest tests/contracts/test_chunks_retrieval.py tests/contracts/test_retrieval_metadata.py -q | 113 passed |
| python -m pytest src/engineering_rag/modules/keyword_retrieval/tests -q | 112 passed |
| python -m pytest src/engineering_rag/modules/vector_retrieval/tests -q | 99 passed |
| python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q | 62 passed |
| python -m pytest src/engineering_rag/modules/query/tests -q | 351 passed |
| python -m pytest src/engineering_rag/modules/generation/tests -q | 10 passed（仅契约） |
| python -m pytest tests/contracts -q | 285 passed |
| python -m pytest tests/architecture -q | 14 passed |
| python -m pytest -q | **1433 passed，25 skipped，0 failed（23.39s）** |
| ruff check . | All checks passed |
| ruff format --check . | PASS，无需重新格式化 |
| git diff --check | 退出码 0，无输出 |

完整日志目录：`data/eval/task7_0_1/runs/validation-20261019/`（01～12 分项日志）。
25 个普通全量测试跳过不等于真实外部能力已验证；本次新增只读测试默认关闭，下面显式
启用独立执行。其余外部测试未在本任务擅自开启，避免写数据库或调用 LLM。

### 真实只读数据库测试

```bash
ERAG_RUN_REAL_RETRIEVAL_METADATA=1 \
ERAG_METADATA_ENV_FILE=.env \
ERAG_METADATA_CORPUS=data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json \
ERAG_METADATA_BASELINE_FILE=data/eval/task6_6/runs/readonly-backends-20261019T020835Z/real-backend-smoke.json \
ERAG_METADATA_OUTPUT=data/eval/task7_0_1/runs/real-readonly-20261019-v2 \
.venv/bin/python -m pytest tests/integration/test_retrieval_metadata_readonly.py -q -s --tb=short
```

最终实际结果：**1 passed，0 failed，0 skipped（17.59s）**。运行会拒绝覆盖已有产物目录；
复测时需指定新输出目录。模型使用已缓存本地 BGE，并强制离线模式，不下载、不调用 LLM。

校验全部 **1305** 条 Chunk 身份、内容及来源存储一致性；命中来源属性逐项与原始 Chunk
比较。查询前后两个后端的完整 inventory hash、条数及语料 hash 相同。真实结果同时包括
正文 false 与说明 true，未知强制性保留 null；true/false 强制性组合由单元测试补足。

Hybrid 历史排名与本次完全一致：

| rank | chunk_id | RRF score | is_explanation |
| --- | --- | --- | --- |
| 1 | chunk-b890e9f9c95b5e14a11f9ffe68f70f04 | 0.01626123744050767 | false |
| 2 | chunk-8f33271e6fb15b87b60953bd3f7d11ce | 0.016009221311475412 | true |
| 3 | chunk-d5c7c0f4561159aa88f395d1c01fb6e6 | 0.015749007936507936 | true |

产物：

- `data/eval/task7_0_1/runs/real-readonly-20261019-v2/report.json`
- 同目录 `query_result.v2.json`、`generation_request.json`
- `data/eval/task7_0_1/runs/validation-20261019/13-real-readonly.log`

第一次只读运行产物保留在 `real-readonly-20261019-v1`，未覆盖。

## 修改文件清单

生产代码（5 个）：

- `src/engineering_rag/contracts/retrieval.py`
- `src/engineering_rag/modules/keyword_retrieval/internal/searcher.py`
- `src/engineering_rag/modules/vector_retrieval/internal/searcher.py`
- `src/engineering_rag/modules/hybrid_retrieval/internal/candidate_merger.py`
- `src/engineering_rag/infrastructure/evaluation/internal/offline.py`（仅离线夹具映射）

新增测试：

- `tests/contracts/test_retrieval_metadata.py`
- `tests/architecture/test_retrieval_metadata_contract.py`
- `tests/integration/test_retrieval_metadata_readonly.py`
- `src/engineering_rag/modules/keyword_retrieval/tests/test_source_metadata.py`
- `src/engineering_rag/modules/vector_retrieval/tests/test_source_metadata.py`
- `src/engineering_rag/modules/hybrid_retrieval/tests/test_source_metadata.py`
- `src/engineering_rag/modules/generation/tests/test_evidence_contract.py`

更新测试：`tests/contracts/test_examples.py`、`tests/contracts/test_query_v2.py`、
`tests/evaluation/test_pipeline.py`、`src/engineering_rag/modules/query/tests/test_pipeline_integration.py`。
原断言仅因获批的 RetrievalResult 版本升级调整，新增旧版本读取/未知值断言，未跳过测试。

示例/文档：新增 `examples/retrieval.v2.example.json`、`docs/adr-retrieval-result-v2.md`、
本报告；更新 README、docs/data-contracts.md、docs/architecture-decisions.md，以及
Keyword/Vector/Hybrid/Query/Generation 的 INTERFACE.md。
历史 `docs/task-7-generation-interface-review.md` 和旧 retrieval 示例未改。

## F. 限制与维护者事项

- 无本任务阻塞、无最终失败。部署前确认仓库外消费者是否已升级；不能承诺未登记外部消费者兼容。
- 不补猜历史缺失属性；历史证据保持 null，需要真实上游重新检索才能获得已存来源属性。
- 未新增 source_refs/source_block_ids 公共字段；既有数据库/Chunk 仍保存它们。
- 未重算历史文档向量、未评估召回率或 Parser 准确率；本任务只证明来源透传与算法不变性。
- Generation 仍未实现；真实 LLM/生成测试 NOT RUN（任务明确禁止），不把本次契约测试当作答案生成验收。
- 维护者验收后可单独启动下一任务；本次在 Task 7.0.1 停止。
