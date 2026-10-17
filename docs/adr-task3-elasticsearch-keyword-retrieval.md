# ADR：Task 3 Elasticsearch 关键词检索

- 状态：Accepted
- 日期：2026-10-17
- 范围：`keyword_retrieval` 模块内部实现，不改变公共契约

## 决策

1. 生产实现使用官方 Elasticsearch Python 8.x 客户端，以物理 `Chunk` 为索引文档，
   Elasticsearch `_id` 固定为 `chunk_id`。
2. Mapping 版本为 `keyword-index-v1`，`dynamic=strict`。全文字段 Analyzer 由
   `ENGINEERING_RAG_ES_ANALYZER` 显式指定，默认使用 Elasticsearch 内置 `standard`；
   配置插件 Analyzer 时由目标集群负责提供插件，创建失败即显式报错，不做降级。
3. 默认 BM25 只查询私有 `search_text`。该字段取现有 `embedding_text`，不把整个 Chunk
   JSON 序列化为检索文本。调用方显式提供权重时，仅允许 `content`、`context_header`、
   `embedding_text` 三个白名单字段。
4. `IndexRequest.replace_document=True` 将非空 `ChunkBatch` 视为该文档完整快照：先 Bulk
   upsert 新快照，全部成功后才删除同 `document_id` 下不在新快照中的旧 Chunk。部分失败
   通过既有 `IndexResult.failures` 返回，并跳过清理。`False` 为增量 upsert。空批次不访问
   索引，也不代表删除请求。
5. 写入使用配置的 refresh 策略，默认 `wait_for`；同一 `chunk_id` 重试为幂等覆盖。
   Elasticsearch 不提供跨 Bulk 和 delete-by-query 的事务，因此“写入成功而陈旧清理失败”
   会抛出可审计异常，调用方可安全重试完整快照。
6. 搜索排序固定为 `_score` 降序、`chunk_id` 升序；`score` 是未归一化的 Elasticsearch
   BM25 `_score`，不能直接与未来向量分数相加。

## 契约限制

索引 `_source` 保存 Chunk V1 的 `source_refs`、`source_block_ids` 等来源数据，但冻结的
`RetrievalResult` 当前没有来源引用字段，因此公开返回值只能返回该契约已有的文档、标准、
条文和页码信息。若上游未来要求逐 Block 引用，必须另行升级公共契约；本任务不私自扩展。

## 已知限制

- 默认 `standard` Analyzer 无需插件，但中文词粒度通常弱于 IK/SmartCN。生产部署可显式
  选择已安装且版本兼容的 Analyzer；已有索引 Analyzer 不一致时必须新建/迁移索引。
- 快照清理使用 `terms` 排除本批 `chunk_id`，受 Elasticsearch 单个 terms 查询上限约束。
- 目标 Elasticsearch 服务版本在当前环境中未配置；客户端约束为 `>=8.15,<9`，真实集群
  兼容性由可选集成测试验证。
