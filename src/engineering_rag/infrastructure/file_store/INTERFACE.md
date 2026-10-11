# File Store 接口（版本化 Document Artifact）

## 职责与非职责

未来 FileStore 持久分配 `file_id`，流式保存原文件，并以不可变快照保存 `document.json + assets/ + manifest.json`。本阶段只有 Protocol 和 DTO，不读写磁盘、对象存储，也不执行版本迁移。

## 公开路径与签名

`engineering_rag.infrastructure.file_store.api` 重导出唯一公共 Protocol：

```python
class FileStore(Protocol):
    def put(self, source: Path | BinaryIO, *, media_type: str) -> FileRef: ...
    def read(self, reference: FileRef | ArtifactRef) -> AbstractContextManager[BinaryIO]: ...
    def exists(self, reference: FileRef | ArtifactRef) -> bool: ...
    def delete(self, reference: FileRef | ArtifactRef) -> bool: ...
    def commit_artifact(self, artifact: DocumentArtifact) -> ArtifactManifest: ...
    def get_artifact(self, artifact_id: str, artifact_version: str) -> DocumentArtifact: ...


class DocumentMigrationService(Protocol):
    def migrate_document(
        self, source: DocumentArtifact, target_schema_version: str
    ) -> DocumentArtifact: ...
```

## 输入输出与校验

`FileRef.file_id` 是持久身份，`sha256` 只校验内容。Manifest 的 `artifact_id + artifact_version` 标识一个快照；Document JSON 与每个 Asset 引用必须含 URI、media type、SHA-256 和大小。DTO 只做静态一致性校验；资源缺失或实际校验和不符属于未来 I/O 完整性错误。

## 错误、部分成功与版本

`commit_artifact` 只接受静态合法的 completed/partial bundle。因为嵌套 Pydantic 对象原地修改不会自动重跑父级全图校验，未来实现必须先用序列化结果重新构造并完整验证 `DocumentArtifact`，然后才计算真实文件 hash、写资源并提交 Manifest。同一快照键内容不一致必须报 `CONFLICT`，不得覆盖。failed Manifest 记录失败身份但不携带合法 Document。旧 Schema 只可经显式 Migration Protocol 转换；不支持的版本、缺资源和校验和不一致必须分别报告。

## 副作用、幂等、排序与依赖

`put` 和 `commit_artifact` 有写副作用。相同快照键与相同内容可幂等返回原 Manifest；相同键不同内容必须失败。只有 Manifest 成功提交后快照才可见。历史快照不可就地修改；`delete` 仅用于未来明确的保留策略，不能模拟覆盖。实现只依赖 contracts 和自身适配器。

## 接口示例

```python
# 接口示例：store 是未来注入实现；本仓库没有真实存储后端。
stored_manifest = store.commit_artifact(document_artifact)
loaded = store.get_artifact(stored_manifest.artifact_id, stored_manifest.artifact_version)
```

Python API 版本 1；Manifest 指向 Document Schema 2.4，Artifact 版本、Parser 版本与标准 edition 相互独立。接口契约测试随全量 `python -m pytest -q` 执行。
