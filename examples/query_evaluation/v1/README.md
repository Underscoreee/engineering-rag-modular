# Query Evaluation 虚构格式示例

本目录：6 个合法 Chunk、8 条 draft 查询、9 条 draft qrels；review_log.jsonl 是空文件。所有语料、编号和数值均为软件测试用途，不来自真实规范，也不代表工程要求。

- dataset_id：query-evaluation-demo
- dataset_version：1.0-draft
- corpus_snapshot_id：fictional-engineering-corpus-v1
- corpus：corpus.chunk_batch.v1.json
- 全部标签未人工核验；manifest.is_test_fixture=true。
- 7 条正常检索查询、1 条未知虚构标准的预期拒绝查询。
- 已覆盖格式：数值、单位、否定、公式、表格、图、条文说明与探索性比较。
- 未覆盖：真实人工质量、多标准、跨页、权威强制性证据、真实模型与数据库。

只读校验可以检查 ID、Schema、计数、哈希与引用；formal=true 必须拒绝本数据集。offline_test 仅验证流程，不提供真实召回质量结论。请按 annotation_guidelines.md 建立人工审阅记录，不要自动生成 human_verified 声明。
