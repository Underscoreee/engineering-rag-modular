# Evaluation 接口

## 职责与非职责

Task 6.5 在既有 EvaluationService 下提供 Query/Hybrid 评估适配器：读取人工标注、校验固定
ChunkBatch 和目标身份、计算确定性指标、执行共享范围的五种消融、保存独立实验。
不修改/生成正式人工标签，不写索引，不实现检索、Embedding 或 Generation。
Parser 的已有质量工具与 Query 金标分离；本适配器不声称已实现其他 evaluation_type。

## 公开 API

导入路径：`engineering_rag.infrastructure.evaluation.api`。

```python
def create_evaluation_service(
    *, runtime: EvaluationRuntime | None = None
) -> QueryPipelineEvaluator: ...


class EvaluationService(Protocol):
    def evaluate(self, request: EvaluationRequest) -> EvaluationReport: ...
```

复用 canonical contracts，不新增 EvaluationRequest/Report/Service。
公开重导出 load_dataset（只读）、DatasetValidationError、IndexSnapshot、EvaluationRuntime。
数据集/实验配置是评估私有格式 1.0，不是公共 Query/Chunk DTO 的替代。

## 输入、校验及错误

EvaluationRequest.evaluation_type 必须是 retrieval；dataset 是既有 ArtifactRef，要求
artifact_type=query_golden_dataset、schema_version=1.0、artifact_id=manifest.dataset_id、
artifact_version=dataset_version=manifest.dataset_version。uri 为本地目录路径，不接受 URL。
正式运行必须提供与 manifest 原字节相符的 dataset.sha256。

config 使用原契约的标量字典；不新建第二套公共配置请求：

| 键 | 必填/默认及作用 |
| --- | --- |
| corpus_path/corpus_snapshot_id | 必填，实际 ChunkBatch 文件和不可混淆的语料快照 ID |
| output_dir/run_id | 必填，运行写入 output_dir/run_id；已有目录绝不覆盖 |
| mode | validate_only（默认）/offline_test/retrieval_eval/llm_e2e_eval |
| variants | 逗号字符串，默认 raw,rewrite,rewrite_expansion,rewrite_hyde,full |
| ks | 逗号正整数字符串，默认 5,10,20；不得重复或超过 candidate_k |
| relevance_threshold | 默认 2，范围 1～3，二元相关性阈值 |
| keyword_index/vector_collection | 非只校验模式需明确配置，绝不自动发现索引 |
| candidate_k | 默认 50，两路共享，最终 top_k=max(K) |
| fusion_strategy/keyword_weight/vector_weight | 默认 rrf/0.5/0.5；复用公共 Hybrid 校验 |
| embedding_model_id | 可选；正式快照必须与实际模型身份一致 |
| snapshot_manifest | 正式运行需提供 IndexSnapshot JSON |
| require_verified | 默认 false；true 使未核验/空金标在加载时直接失败 |
| code_revision | 可选，组合根应提供真实版本，不推测 Git 提交 |

未知 config 键、非法参数、版本/哈希/目标错误抛明确 ValueError/ValidationError 或
DatasetValidationError（含路径/行号/身份），不自动修复数据。Dataset loader 不写文件。
无效 qrel 直接使运行失败，绝不能计为检索未命中。
正式模式缺人工金标、可信快照或运行依赖时保存 NOT RUN，public metrics 为空并记录失败。
逐查询后端故障、安全异常与正常无命中分开；异常类型/代码保留，不默认保存可能含凭据的异常全文。

## 数据集与来源绑定

目录包含 manifest.json、queries.jsonl、qrels.jsonl、review_log.jsonl、annotation_guidelines.md。
manifest 绑定四份文件原字节 SHA-256、ChunkBatch SHA-256、语料/Chunking/Schema 版本和数量。
Query 注释复用 ProcessingIntent、SearchFilters、ConversationTurn；原始 caller_filters 与
expected_filters 分开，不能把期望值喂给 Understanding 来抬高分数。
protected_spans 是 Python 字符 [start,end) 与原文精确一致；重复同区间同类别拒绝。
qrels 等级严格整数 0～3，重复/悬空引用拒绝；全部正 gain（>0）目标须在预期过滤范围内。

正式金标要求 query/qrel 全部 verified、对应真实人工 review_id、复核者/时间/理由和目标一致，
每个正常查询具有有效相关目标。人工记录只是可信维护者声明，不是程序可鉴定的人类身份证明。
is_test_fixture=true 永远不能产生正式指标。未经核验的示例可做显式 offline_test，不会被升级。

source_document_id/hash/source_pdf_sha256 可审计保留；缺原 Document/PDF 路径时仅为来源声明，
不能宣称程序独立验证其真实性。首版只读取一个 canonical ChunkBatch，真实跨文档/多标准
评估需独立设计多批次语料清单，不能伪造同一个 batch.document_id。

## 依赖注入、消融与真实模式门禁

EvaluationRuntime 由可信组合根显式构造，包含：backend_kind、hybrid_service、可选 query_factory、
llm、llm_kind、verify_snapshot 与无凭据版本 metadata。QueryFactory 签名为
`(variant, observed_llm, guarded_hybrid) -> QueryService`；必须使用传入的模型/检索依赖，
并由各业务模块公开 API 创建服务。Evaluation 核心不导入业务 internal 或创建外部客户端。
offline.py 是明确隔离的虚构演示组合根，仅使用公开 Query/Hybrid API；不是生产存储替代。

| 变体 | 真实行为 |
| --- | --- |
| raw | 原问题直接提交两路，使用相同人工预期过滤；不调用 Query/LLM；预期拒绝样本显式 skipped |
| rewrite | 实际 Query 服务，两种增强关闭 |
| rewrite_expansion | 仅 Expansion 开启；探索性没有实际使用扩展则变体失败，不冒充成功 |
| rewrite_hyde | 仅 HyDE 开启；探索性没有实际使用 HyDE 则变体失败 |
| full | 实际 Query 完整策略，允许其合法可选增强降级 |

每次只 execute 一次，不先 plan 再 execute。Acquisition 按正常策略跳过两种增强。
所有变体的实际 filters 必须等于同一人工范围，否则在到达后端前报告 scope_mismatch；
不覆盖错误预测来凑公平对照。预算、索引、模型 ID、融合和权重也必须一致。
结果内容及文档/条文/页码身份逐一匹配固定语料，未知、重复或来源不同的命中拒绝计分。

retrieval_eval 首版执行 raw；其他变体明确 not_run，不能用 Fake LLM 当真实改写。
llm_e2e_eval 需要实际模型和 Query 工厂。两种真实模式都要求全量核验标签、真实依赖声明、
IndexSnapshot，以及注入 verify_snapshot 对当前实际索引 inventory/version 的只读核验。
索引名不是快照；corpus hash、Chunk ID inventory hash、文档、双索引版本及模型编码策略必须
匹配。缺真实适配器时 NOT RUN，不默认用地址或预填 JSON 声称核验成功。
依赖身份与 verifier 是可信组合根边界，不能鉴别任意恶意 Python 工厂。客户端生命周期归调用方。

## 指标、未知量与产物

排名：Recall/Precision/MRR/nDCG/HitRate@K。二元阈值默认 >=2；Precision 分母固定 K，
短结果不改分母；nDCG gain=2**grade-1、discount=log2(rank+1)。无效分母 null；未判定命中
按 0 gain 的约定并不证明标注充分，需记录池化/覆盖偏差。相同 Chunk 重复命中拒绝。
意图：Accuracy、两类 precision/recall/F1、固定两类 macro-F1、混淆矩阵；有效但全错时 F1=0。
过滤：七字段集合精确率/召回率/漏约束/额外约束，false 与 null 区别；范围违规单列。
Rewrite：按原查询人工保护项计算逐查询精确保留，再汇总分类；不把字面保留当语义等价证明。
增强：分别记录实际阶段状态、已接受输出数量/保护项、合法空列表与失败、关闭/按意图跳过。
明显无关/新事实真实性/人工语义等价未经独立标注时为 null，不用模型自评冒充人工。

模型装饰器记录公开请求配置、Prompt 版本、调用耗时/用量，raw response 只作候选摘要，
不当作接受结果。临时标准 logging handler 仅收集同 trace 的既有安全元数据并恢复 logger，
用于读取阶段校验后的状态；日志不可观测时标记 not_observed，不伪造状态。
后续失败仍可从 Rewrite 的公开输入观察已核验 Understanding 预测；未观测到则单列缺失。
此评估入口顺序执行；不要同时修改其依赖的 logger 配置。完整阶段事件与模型调用耗时分开。
用量缺失或失败调用用量未知时为 null；无可信计费价格/账单时成本为 null，不估算实际费用。

输出 config.json、metrics.json、per_query_results.jsonl、evaluation_report.json、report.md。
模拟分数只在 offline_simulation，official_quality_metrics=null 且公共 report.metrics=[]；
NOT RUN 也不发布正式分数。失败样本全部保留，平均分记录实际样本数/null 数；配对对比
固定相同查询人口，改善/退化/持平和未比较数分开，无 Bootstrap 时不宣称显著改善。
产物包含问题/已接受文本与证据，应受控保存，不是默认日志。

## 调用、版本与独立测试

最小代码调用：由组合根构造既有 EvaluationRequest 后调用
`create_evaluation_service(runtime=runtime).evaluate(request)`；只校验时可不提供 runtime。
完整可运行 CLI、标注步骤、版本更新与已知限制见
[Task 6.5 使用说明](../../../../docs/task-6.5-query-evaluation.md)。

```bash
python -m pytest tests/evaluation -q
python -m pytest src/engineering_rag/modules/query/tests -q
python -m pytest src/engineering_rag/modules/hybrid_retrieval/tests -q
python -m pytest tests/contracts tests/architecture -q
python -m pytest -q
ruff check .
ruff format --check .
git diff --check
```

公共 Evaluation 契约仍 1.0，Query 仍 2.0，Document Frozen 2.4 与 Chunk 1.0 不变。
当前交付只有演示与待人工标注队列，没有真实质量提升结论。

