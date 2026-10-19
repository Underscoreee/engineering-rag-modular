# Task 6.6：真实 LLM 与 Query → Hybrid 检索

验收日期：2026-10-19。总体 **PARTIAL**：真实后端、Embedding 和直接 Hybrid Smoke 已验证；
真实 DeepSeek 与完整 Query.execute 因缺少 `ERAG_LLM_API_KEY` 为 **BLOCKED / 未执行**。
没有人工 Query 金标，不计算或宣称真实检索质量提升；没有进入 Generation。

## 1. 改动与数据流

```text
显式 .env / 进程环境
  → 真实 LLM 配置校验 / 可选一次结构化 API smoke
  → ChunkBatch 字节 SHA + Pydantic 校验
  → ES / Milvus 完整只读库存、Schema、模型身份比对
  → 已核验语料 Catalog（不是测试目录）
  → 现有 Query 工厂：Understanding → Rewrite → Expansion / HyDE → Planning
  → 现有 Hybrid → Elasticsearch BM25 + Milvus / 本地 BGE
  → 公共 QueryResult V2.0 + 独立运行诊断
```

只调用一次 `execute(request)`，不先 `plan()` 再执行。没有新增 Query/Hybrid 实现、检索
算法或公共 DTO；Document Frozen 2.4、Chunk V1、Retrieval V1、Query V2 和 Protocol 均未改。

新增基础设施 `infrastructure/llm/` 提供 `LLMSettings`、`OpenAICompatibleLLMClient` 和可注入
HTTP Transport；仅依赖标准库和既有 Pydantic。接口与错误细节见
[LLM INTERFACE](../src/engineering_rag/infrastructure/llm/INTERFACE.md)。
CLI 与两个 `_query_smoke_*.py` 为组合入口，只使用公共契约、公开 API 和官方客户端操作，
不导入业务模块 internal。Query 模块内部实现未修改。

## 2. DeepSeek 配置和安全

在仓库根目录使用已有可编辑安装的 `.venv`；缺少依赖时按照 README 安装
`.[dev,keyword-retrieval,vector-retrieval]`。无需安装 OpenAI SDK 或新增 LLM 依赖。

```bash
cp .env.example .env
# 使用本地编辑器填写 .env 的 ERAG_LLM_API_KEY；不要贴进聊天或命令参数。
.venv/bin/python scripts/query_retrieval_smoke.py --env-file .env --config-only
```

`.env.example` 包含 DeepSeek endpoint、示例模型、变量说明及当前实际后端名称：

| 配置 | 说明 |
| --- | --- |
| `ERAG_LLM_PROVIDER=deepseek` | 单个 OpenAI-compatible Chat Completions 适配器 |
| `ERAG_LLM_BASE_URL=https://api.deepseek.com` | 自动追加 `/chat/completions` |
| `ERAG_LLM_API_KEY` | 本地填写，示例中为空 |
| `ERAG_LLM_MODEL=deepseek-flash` | 当前官方文档的示例模型，须确认账户可用；本轮未实际调用 |
| `ERAG_LLM_RESPONSE_FORMAT=json_object` | DeepSeek JSON 模式，不是原生完整 JSON Schema 保证 |
| `ERAG_LLM_TIMEOUT_SECONDS=30` | 示例 socket 操作超时；不是整个流程的严格总时限 |
| `ERAG_LLM_MAX_ATTEMPTS=2` | Understanding / Rewrite 各阶段的共享尝试预算，1–2 |
| `ERAG_LLM_MAX_OUTPUT_TOKENS=2048` | 示例生成上限；具体请求使用其 StructuredLLMConfig |

其余温度、Token 参数名、可选响应模型别名、期望 revision、Embedding 和后端变量均在
`.env.example` 及接口文档列明。远端版本默认 null，不能用请求值或 fingerprint 伪造版本。
DeepSeek 接口地址和示例模型依据[官方首次调用文档](https://api-docs.deepseek.com/)；
JSON 模式要求明确 JSON 指令，并仍需本地 Schema 校验，见
[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/)。
OpenAI 原生 strict Schema 与 JSON 模式的差异参考
[OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat)。

每次 generate 仅一次 POST，无隐藏 HTTP 重试；Query 既有重试/纠正预算保持不变。
请求/响应绑定模型与 ID；每个 Query 阶段继续执行 `response.validate_output()`，不能只相信
供应商的 JSON 声明。通用 json_schema 仅在显式验证支持的其他兼容端点启用，DeepSeek 拒绝
该选项。认证、额度、限流、服务端、连接、超时、截断等错误明确分类，不输出原响应体。

`.env` 被忽略，只有 `.env.example` 允许纳入 Git。CLI 仅显式读取所选配置文件，既有进程
环境优先；只支持字面 KEY=value / 单双引号及整行注释，不执行 shell 或变量展开。不会扫描
其他凭证文件。密钥用 SecretStr 保存，诊断不含密钥/认证头；写文件及打印前再次拒绝已知
密钥及其 JSON 转义形式。禁止凭据 URL、重定向认证转发和隐式代理环境发现。

调用真实 LLM 会将 Query 的问题、有界历史、已批准规则/候选约束及输出 Schema 发给
配置供应商，可能收费；本入口不发送整份 PDF、Document 或检索命中全文。`--llm-smoke`
显式授权一次最小调用；`--question` 显式执行有预算的真实 Query 调用。普通 pytest 不调用 API。

## 3. 真实只读运行命令

以下路径均为仓库内相对路径，输出目录必须是新目录。`--config-only` 不联网、不加载模型。
默认只使用本地 Hugging Face 缓存；确需下载须显式传 `--allow-model-download`。

先只做前置检查（不执行 Query）：

```bash
.venv/bin/python scripts/query_retrieval_smoke.py \
  --env-file .env \
  --corpus data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json \
  --preflight-only --llm-smoke \
  --backend-query '普通钢筋疲劳应力幅限值如何取值？' \
  --output-dir data/eval/task6_6/runs/my-real-preflight-001
```

有效 Key 配好后，单查询完整链路（本轮尚未实际执行成功）：

```bash
.venv/bin/python scripts/query_retrieval_smoke.py \
  --env-file .env \
  --corpus data/eval/task2/runs/GB50010-full-v6-semantic-cleanup/chunk_batch.v1.json \
  --llm-smoke \
  --question 'GB 50010-2010 第 4.2.6 条普通钢筋疲劳应力幅限值如何取值？' \
  --top-k 3 --candidate-k 10 \
  --filters-json '{"document_ids":["doc-dab4ba42814d5a878df723d32b346337"],"editions":["2015年版"]}' \
  --trace-id task66-query-001 \
  --output-dir data/eval/task6_6/runs/my-real-query-001
```

可用 `--disable-expansion` / `--disable-hyde` 关闭既有增强开关；默认按现有策略开启。
acquisition 正确跳过增强，exploratory 才尝试增强。不能用关键词强行指定模型意图。
`--full-content` 展示完整命中正文，否则摘要最多 240 字符。不要把假设文本当作命中证据。

运行输出：

- `preflight.json`：逐项 PASS / FAIL / NOT RUN / BLOCKED。
- `diagnostics.json`：模型调用元数据、实际 Query logger 事件、耗时、策略、错误与摘要；
  未出现的阶段事件不凭模型候选推测。问题只在显式 CLI 交互/受控报告中展示，不写适配器日志。
- `query_result.v2.json`：仅在 execute 成功且来源核验通过时生成，严格公共 QueryResult，
  不增加诊断字段；正常零命中可保存实际空 evidence，但不满足本次至少一条命中的验收门槛。

退出码：配置检查成功为 0；完整端到端至少一条真实命中为 0；失败/阻塞/未完成真实验收为 2。
仅配置成功或只通过部分 preflight 不代表整体端到端 PASS。不会覆盖任何既有运行目录。
RetrievalResult 本身没有 bbox/source_refs；报告保留其真实标准/条文/物理页，Chunk ID 绑定
到已核验语料中的原始 source_refs，不伪造公共字段。

## 4. 本轮真实环境和结果

仅 `docker compose -f docker-compose.elasticsearch.yml start` 及
`docker compose -f docker-compose.milvus.yml start` 恢复本仓库原容器。
四个容器现 running/healthy，留在运行；无 pull/up、重建、删卷、重建索引或数据库写入。
本机无认证环境只绑定回环地址，不能用于公网部署。

| 项目 | 实际结果 |
| --- | --- |
| 配置供应商 / 模型 | DeepSeek / deepseek-flash 示例；无有效 Key，实际 API NOT RUN |
| Elasticsearch | 8.19.0；engineering-rag-gb50010-v6；1305 Chunk |
| Milvus | 2.5.4；engineering_rag_gb50010_full_v6；Strong 逻辑数 1305 |
| 数据身份 | 1 Document，1305 唯一 ID；双后端与本地语料缺失 0 / 多余 0 |
| 模型 | BAAI/bge-small-zh-v1.5，revision 7999e1d3359715c523056ef9478215996d62a620 |
| 向量 | 512 维、有限、归一化；COSINE；HNSW M=16 / efConstruction=200 |
| 查询指令 | 为这个句子生成表示以用于检索相关文章： |
| 来源快照 | SHA-256 49daa3d96006149b62b5887f72082d27a23e37ce15aeb50349807680d800f162 |

只读库存检查对比 ES 完整存储 Chunk（包括 search_text）、Milvus 全部既有内容/元数据/
provenance，验证 UUID / Collection ID、模型身份和索引参数。不只是比较数量；ES 使用完整
Scroll，Milvus 使用 Strong count(*) 和完整 Iterator，不以 10000 条上限掩盖遗漏。
只有核验成功才构建单快照目录；未知/额外文档、身份漂移或同维度不同模型均拒绝。
这里不重新计算并逐个证明已有向量值，也不声称数据库跨系统原子快照。

启动早期 Milvus stats 曾返回 2610，而 Strong 和完整 ID 库存为 1305；之后 CLI 查询 stats
也为 1305。统计单独记录，不据此推断 2610 个活跃 Chunk 或断言未取证的内部历史原因。

真实本地模型已编码 2 条文档 + 1 条查询，通过维度、有限值和归一化检查；冷加载+编码
185.854 秒。CLI 后续进程缓存加载+查询编码约 9.841 秒，不是纯 ANN 耗时。

真实只读问题“普通钢筋疲劳应力幅限值如何取值？”：

| 服务 | 命中 | 实际耗时 | 首条 |
| --- | --- | --- | --- |
| BM25 | 3 | 0.122 秒 | chunk-b890e9f9c95b5e14a11f9ffe68f70f04，33.344112 |
| Vector | 3 | 8.378 秒（含模型初始化） | chunk-8f33271e6fb15b87b60953bd3f7d11ce，0.7247143388 |
| Hybrid RRF | 3 | 0.646 秒 | chunk-b890e9f9c95b5e14a11f9ffe68f70f04，0.01626123744050767 |

Hybrid candidate_k=10/top_k=3；首条为正文 Clause 4.2.6，物理页 40–41。分数来自真实服务，
BM25/cosine/RRF 未直接相加或改成同一分数。
这是直接后端/Hybrid Smoke，不是完整 Query.execute，也不是人工相关性评估。

真实产物：

- `data/eval/task6_6/runs/readonly-backends-20261019T020835Z/`：恢复、完整库存、真实模型、
  BM25/Vector/Hybrid 结果、日志和报告。
- `data/eval/task6_6/runs/config-missing-key-20261019-v1/`：实际配置检查，仅缺 API Key。
- `data/eval/task6_6/runs/real-preflight-20261019-v1/`：本次新 CLI 使用真实语料的完整 preflight；
  库存、Embedding、BM25、Vector PASS；LLM、Assembly、Query E2E BLOCKED，退出 2，未生成伪结果。

## 5. ADR-Q-006：最小真实运行边界

1. LLM 放在 infrastructure，不把 SDK/凭据加入 Query 或公共契约；统一一个兼容适配器。
2. DeepSeek 使用 JSON 模式 + 应用本地校验。供应商 strict Schema 支持必须另行实际验证；
   wire Schema 变换只操作深拷贝，不改原始契约 Schema。
3. 目录只由实际 ChunkBatch + 双后端完整相等库存构建；不将 FixtureCatalog 改标记冒充生产。
4. 运行统计属于 sidecar，不给 QueryResult 添加字段。不复用要求人工金标的正式 evaluator
   来声称 Smoke 具有质量指标；Evaluation 私有遥测也不由脚本跨层导入。
5. 当前向量入库实现实际编码 `chunk.content`，查询编码采用现有 query_instruction + 查询文本。
   本轮不修改为 embedding_text，不重算已有向量；Collection 描述未独立记录此文本策略，
   作为后续兼容性检查项记录，不声称已验证每条历史向量的输入文本。

## 6. 测试与未完成事项

基线 `.venv/bin/python -m pytest -q`：987 passed / 24 skipped，32.61 秒。
修改后实际结果（无失败）：

| 命令 / 范围 | 实际结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/infrastructure/llm -q` | 64 passed |
| `.venv/bin/python -m pytest tests/integration/test_query_retrieval_smoke.py tests/integration/test_query_smoke_backends.py -q` | 52 passed，全部离线注入测试 |
| 阶段 A：上述新增测试 + Query + Hybrid + tests/contracts + tests/architecture | 680 passed，14.29 秒 |
| `.venv/bin/python -m pytest -q` | 最终复跑 1103 passed / 24 skipped，36.47 秒（前次 41.75 秒） |
| 七个业务模块分别独立运行 pytest | 全部通过，逐模块日志见 validation 目录 |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/ruff format --check .` | 383 files already formatted |
| `git diff --check` | 退出 0，无输出 |
| 真实 LLM / 完整 Query E2E / 人工金标多查询评估 | 未运行成功；不得计为通过或离线测试的替代 |

完整阶段 A 命令：

```bash
.venv/bin/python -m pytest \
  tests/infrastructure/llm \
  tests/integration/test_query_retrieval_smoke.py \
  tests/integration/test_query_smoke_backends.py \
  src/engineering_rag/modules/query/tests \
  src/engineering_rag/modules/hybrid_retrieval/tests \
  tests/contracts tests/architecture -q
```

上述测试输出保存在 `data/eval/task6_6/runs/validation-20261019/`，包括 full-pytest、stage-a、
llm-unit、smoke-offline、module-*、ruff-check 和 ruff-format 日志。
最后一次源码调整后另保存 `full-pytest-final.log`（1103 / 24）和
`adapter-cli-final.log`（116 passed）；前次完整日志不覆盖。
普通完整 pytest 的既有真实测试需要显式配置，因此 skip 不能算通过；本轮真实后端验证
以独立运行产物为证据，不声称这些被跳过的测试已执行。

修改文件清单：

- `.env.example`、`.gitignore`：唯一配置示例与安全忽略规则。
- `src/engineering_rag/infrastructure/llm/`：api、config、内部 adapter/transport/serialization/
  errors、包初始化和 INTERFACE（9 文件）。
- `scripts/query_retrieval_smoke.py`、`scripts/_query_smoke_runtime.py`、
  `scripts/_query_smoke_backends.py`：真实单查询入口、受控配置/诊断和只读库存目录。
- `tests/infrastructure/llm/test_adapter.py`、`test_transport.py`：64 项离线适配器测试。
- `tests/integration/test_query_retrieval_smoke.py`、`test_query_smoke_backends.py`：52 项离线
  CLI、来源、完整库存、错误和安全回归；没有把它们称为真实集成通过。
- `README.md`、`scripts/README.md`、`src/engineering_rag/modules/query/INTERFACE.md`、本报告：
  更新真实入口与当前状态。没有新增依赖，没有改任何业务算法或公共模型。

未完成：填写本地 Key 后执行一次真实结构化 API + 单条 Query.execute，并验证 acquisition /
exploratory 的真实模型路由。当前未提供真实 LLM 的意图、Rewrite、Token 或总耗时数值。
没有人工核验 queries/qrels，正式多查询质量评估 NOT RUN；不自动把本轮召回当作金标。
严格字符区间证据、受控改写和增强仍由现有 Query 检查；真实模型可能被安全门拒绝，不能在
适配器默改 offset、放宽断言或回退原问题伪称成功。
