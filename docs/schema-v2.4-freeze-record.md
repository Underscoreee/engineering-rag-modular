# Document Schema V2.4 正式冻结记录

## 发布结论

- Schema：Document Schema V2.4
- 状态：**FROZEN**
- 冻结日期：2026-10-11
- 批准依据：项目维护者已明确确认 Architecture Task 0.2 修复验收通过，并正式授权 Freeze Release。
- 权威验收表：`docs/schema-freeze-checklist.md`
- Git 修复基线：`d7b23d0`（`fix(schema): address v2.4 freeze review gaps`）
- Git 冻结标识：annotated tag `document-schema-v2.4`；冻结提交 SHA 以 `git rev-parse document-schema-v2.4^{commit}` 的解析结果为准，避免冻结提交在自身内容中形成 SHA 自引用。标签仅在本地创建，未推送远程。

## 权威公共入口

公共 Schema 与 Protocol 的唯一权威 import 根为：

```python
from engineering_rag.contracts import (
    ArtifactManifest,
    ChunkBatch,
    ChunkingConfig,
    ChunkingService,
    Document,
    DocumentArtifact,
    DocumentMigrationService,
    DocumentParser,
    FileStore,
    ParseRequest,
)
```

冻结相关核心 Protocol 签名为：

```python
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...


class ChunkingService(Protocol):
    def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch: ...


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

这些签名定义能力边界，不表示业务算法或后端已经实现。

## 七项已采纳 ADR

1. **ADR-001 稳定 ID 与身份作用域**：区分 File、Document、Artifact 和快照内实体身份，禁止以 OCR 文本哈希替代稳定 ID。
2. **ADR-002 部分解析 Artifact 与 Manifest**：不可变版本化快照，静态完整性声明和显式迁移边界。
3. **ADR-003 PDF 库与 Golden Dataset 边界**：PyMuPDF 仅作为后续评估方向，真实数据集和实现不进入公共契约。
4. **ADR-004 raw_grid 与规范化表格视图共存**：顶层 `tables[]` 是跨页逻辑表权威来源，同时保留可空原始格网和检索展开视图。
5. **ADR-005 引用式 ContentUnit 与 plain_text 缓存**：ContentUnit 只引用权威对象，派生文本带 renderer 版本和来源摘要。
6. **ADR-006 mandatory_evidence**：强制性结论使用三态值和可审计、可核验的证据结构，不由词面自动推断。
7. **ADR-007 延后精简**：只实施已确认删除项，保留 `structure_path`、processing、Asset 版本、`page_count` 与 `ocr.text`。

## 冻结测试证据

冻结前在 Python 3.11.17、Pydantic 2.14.0、pytest 8.4.2、Ruff 0.17.0 环境执行：

| 检查 | 结果 |
|---|---|
| 六项缺陷定向测试 | `6 passed` |
| 全部契约测试 | `114 passed` |
| Document Parser 独立测试 | `1 passed` |
| Chunking 独立测试 | `1 passed` |
| 其余五业务模块独立测试 | 各 `1 passed` |
| 完整 pytest | `127 passed` |
| `ruff check .` | 通过 |
| `ruff format --check .` | `112 files already formatted` |
| 完整/部分 Document 与部分 Artifact 回环 | 通过 |

独立评审提出的六项缺陷已关闭：正文/说明页来源分区、完整 OCR 状态一致性、公式符号说明渲染、Manifest Parser 版本一致性、Asset 摘要与大小一致性、Section 路径与编号一致性。

## 兼容性政策

- V2.4 冻结后不得修改已验收的 Pydantic Schema、公共 Protocol 或数据验证逻辑。
- 兼容的文字澄清、测试补强和不改变序列化/校验行为的维护可以保留在 V2.4。
- 任何字段删除、重命名、类型收窄、验证语义改变或 Protocol 破坏性调整，必须升级 Schema 版本、记录新 ADR，并提供显式迁移机制。
- `2.4-proposal`、V2.3 与 Task 0.1 候选不能静默当作冻结 V2.4；必须显式识别和迁移。
- 持久化 Artifact 以 `artifact_id + artifact_version` 表示不可变快照，历史版本不得覆盖。

## 实现边界

本次发布只冻结公共数据契约、Protocol、文档、示例和契约测试。没有实现 PDF 解析、OCR、表格/公式识别、Chunking、检索、LLM、外部存储后端或迁移算法。Document Parser 的独立实现尚未开始，必须等待维护者启动后续任务。
