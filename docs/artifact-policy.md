# Document Artifact 策略

## 快照布局与提交

未来每个解析快照采用：

```text
<artifact_id>/<artifact_version>/
├── document.json
├── assets/
└── manifest.json
```

快照不可就地覆盖；同一键相同内容可幂等返回，不同内容必须冲突。只有所有内容写入并验证、Manifest 最后成功提交后，completed/partial 快照才对读取方可见。中断状态不得冒充完成。

## Manifest 静态契约

`ArtifactManifest` 区分 Document schema、Artifact version、Parser version 与标准 edition。`created_at` 必须为 UTC；document JSON 和资产引用必须有 URI、media type、SHA-256 与大小。`processing_status` 为 completed/partial/failed，并与 Document.processing 一致。partial 文档的未处理页不是空白，缺少的 OCR/格网/LaTeX 不得伪造。

Pydantic 只验证声明值之间的一致性，不打开 URI、不比较实际字节、不确认资源存在。未来 I/O 实现应分别报告 not found、checksum mismatch、unsupported version 与 commit conflict。

## 迁移

导入 V2.3、`2.4-proposal` 或 Task 0.1 候选必须显式调用 `DocumentMigrationService.migrate_document(source, target_schema_version)`。本任务只声明 Protocol 与目标版本检查，不提供迁移执行器，也不猜测缺失 OCR、表格格网、公式编号或强条证据。转换结果必须产生新的 Artifact 身份并保留来源迁移记录。

## 生命周期

FileStore 的 `delete` 仅供未来明确保留/合规策略，不得用来模拟更新或覆盖历史。真实权限、事务、垃圾回收和后端布局是基础设施实现细节，不进入 Document DTO。
