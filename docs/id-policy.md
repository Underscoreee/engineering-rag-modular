# Document V2.4 ID 策略

## 身份层级与作用域

| 身份 | 语义 | 作用域 |
|---|---|---|
| `FileRef.file_id` | FileStore 持久分配的文件身份 | 文件目录；SHA-256 仅校验内容 |
| `Document.document_id` | 一个具体标准版次的文档身份 | 文档目录；不等于 standard code |
| `artifact_id + artifact_version` | 一次不可变解析输出快照 | Artifact 存储 |
| Block/Section/Clause/Table/Formula/Evidence ID | 快照内实体 | 单个 Document Artifact |

同一 `document_id` 可以有多个 Artifact。只带 `block_id` 等局部 ID 的引用只能在当前快照解析；跨快照引用必须同时携带 Artifact 身份，否则禁止。序列化往返不得改变任何 ID。

## 稳定性规则

Section、Clause 与 Table 优先使用正文/说明命名空间、规范编号、结构路径及必要的确定性来源锚点；重复编号必须确定性消歧。Block 优先使用 page number 和稳定版面锚点。真实分配可采用持久映射或命名空间算法，但属于 Parser/FileStore 内部。

OCR 文本变化不自动创建新 Clause，也不能把 OCR 文本 hash 当稳定 ID。重新分块导致锚点变化时，Parser 应显式保存映射或承认 Block ID 改变，不能无证据声称跨版本稳定。正文与说明即使同号也使用不同 Clause ID。

## 引用完整性

`validate_document_references()` 校验快照内 ID 唯一、Section 无环、Clause/Section 分组、来源 Block、Table 双向片段、Formula、Asset、Evidence 及页范围。`Clause.source_block_ids` 必须等于按 ContentUnit 顺序首次出现去重的来源序列。partial 只放宽未声明内容，不放宽悬空引用。

`DocumentArtifact` 校验 Manifest 的 `source_document_id/schema_version/processing_status` 与 Document 一致，防止同 document 的不同 Artifact 被误当成同一来源快照。具体跨版本映射算法留给后续实现。
