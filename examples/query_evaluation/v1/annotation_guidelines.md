# Query 相关性人工核查规范（示例 v1）

本目录仅含虚构软件测试语料。全部查询和相关性标签为 draft；review_log.jsonl 留空，没有任何人工核验声明。不得将离线演示分数用于真实系统质量结论，也不得用于实际工程设计。

## 核查对象与相关性等级

审阅者须先查看固定语料快照中 Chunk 的 content、context_header、来源、正文/说明身份及完整上下文，再独立判断问题是否可以由该 Chunk 支持。检索结果只帮助发现候选，模型输出、HyDE 和自动标签都不是金标。

- 0：无关，或与问题范围冲突。
- 1：弱相关，只有背景或关键词，不能支持问题。
- 2：相关，可以支持问题的部分要求或比较中的一个对象。
- 3：核心证据，直接支持问题的主要要求。

多个 Chunk 共同支持答案时分别标注；不要仅因为排名高而给高分。没有核验的候选保留 draft/pending，不确定或有争议的标签标记 disputed 并记录复核理由。

## 工程语义检查

正文条文与条文说明是独立证据；提问要求说明时，不可默认把正文当成说明。公式须检查编号、LaTeX、符号定义和适用条件；表格须核查完整表头、数据及表注；图片须结合图名和真实图形来源，不能仅根据编号判相关。

跨页内容须沿 source_refs 检查全部物理页；本虚构语料没有跨页样例，不能据此证明真实跨页检索效果。跨标准比较须逐个核验标准、版次及文档身份；本语料只有一个虚构标准，跨标准覆盖为空。

is_mandatory=null 表示未判定，不能根据“不得”“应”等文本补成 true/false。本示例全部为 null，没有权威强制性证据。应保留数值、单位、否定、适用条件和范围；不得因为自动改写流畅就认定语义等价。

## 查询、范围与失败预期

核查 processing_intent、expected_filters 和 protected_spans。protected_spans 使用原问题的 Unicode 字符 [start, end) 区间，必须逐字对应。caller_filters 是真正输入；expected_filters 是人工期望，不能为了修正模型输出而注入非调用方约束。

显式标准不存在、身份歧义等应失败查询使用 expected_outcome=reject 与明确 expected_error_code，不添加 qrels；不得将拒绝计为普通无命中。正常检索查询应至少有一个经过核验的 relevance>=2 目标。

## 复核与版本流程

1. 从 chunk_id 打开目标 Chunk，确认其确实位于 manifest 绑定的 corpus_snapshot_id 和 corpus_sha256 中；核对 Chunking、Document、索引版本，禁止借用其他快照的 ID。
2. 人工修改查询、范围、保护项或 qrels，并记录充分理由。AI 可协助整理，但不能代签审阅者。
3. 实际审阅者在 review_log.jsonl 写入唯一 review_id、query_id、可空 chunk_id、reviewer、human_verified=true、带时区 reviewed_at、decision 和 rationale；只有本人实际核查后才允许填写该布尔声明。
4. 被核验记录使用 annotation_status=verified 并引用对应 review_id；争议记录引用 decision=disputed 的复核记录。查询级 review 的 chunk_id 为 null，qrel review 指向确切 Chunk。
5. 发布新的 dataset_version 与 corpus_snapshot_id（语料改变时）；重新计算 queries.jsonl、qrels.jsonl、review_log.jsonl、annotation_guidelines.md 及语料文件的 SHA-256，更新清单计数。不得覆写旧实验或旧发布版本。
6. 先运行只读校验，再运行正式评估。形式上的 human_verified 声明并不能替代真实的人工工作；本例不得自动升级为正式金标。

正式使用需另建真实人工数据集、可信索引快照和真实后端配置。本目录保留 is_test_fixture=true，不冒充真实规范或真实人工质量评估。
