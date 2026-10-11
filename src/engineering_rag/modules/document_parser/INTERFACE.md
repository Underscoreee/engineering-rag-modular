# Document Parser 接口（Document V2.4 冻结候选）

## 职责与非职责

未来 Parser 负责从源 PDF 识别物理页类型、Block、Section、正文/说明 Clause，以及跨页表格的逻辑聚合，输出合法 V2.4 `Document`。Task 0.2 没有 PDF/OCR、表格或公式识别实现。Parser 不调用 Chunking，不写检索索引，也不凭措辞判定强制性。

## 公开路径与签名

`engineering_rag.modules.document_parser.api` 重导出 `engineering_rag.contracts.protocols.DocumentParser`：

```python
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...
```

`ParseRequest.source_file: FileRef` 必填；`supplied_standard`、`config`、`trace` 可空。返回值必须是 `schema_version="2.4"` 的完整或部分 Document。表格的完整结构仅在顶层 `tables[]`；Page Block 只保存物理片段。公式的权威内容在公式 Block；Clause ContentUnit 只引用 Block/Table/Formula/Asset。正文证据只有经过外部人工或权威流程核验后才能写入 `mandatory_evidence`。

## 校验、错误和部分成功

Pydantic 字段错误或悬空引用抛 `ValidationError`；未来实现对资源不存在、不支持格式及读取失败须明确报错，不得返回伪成功。部分输出设置 `processing.partial=true`；若 OCR 也未完成，则设置 `is_complete_document_ocr=false`。逐页标记提取状态；未处理页的空 blocks 不等于空白。`raw_grid=null` 不等于没有表格，未识别公式保留 `formula_id` 且 `latex=null`。不填造数据、LaTeX、格网或证据。

## 副作用、幂等、排序与依赖

`parse` 读取源文件，不写索引。相同源文件、配置和实现版本应可重复；稳定 ID 由持久身份/来源锚点策略分配，禁止把 OCR 文本哈希当身份。Block 以本页 `reading_order`、Table fragment 以 `fragment_index`、Clause unit 以 `order` 排序。实现仅依赖 contracts、自身 internal 和注入的 `FileStore` Protocol；导入 API 不接触外部服务。

## 接口示例与版本

```python
# 接口示例：parser 为未来注入实现，本仓库尚无业务实现。
document = parser.parse(parse_request)
```

Python API 版本 1；Document 持久化 Schema 为 **2.4 冻结候选**。Task 0.1 的 ContentUnit 是不兼容候选格式；旧版及 `2.4-proposal` 必须显式迁移和核验，破坏性变更另立版本和 ADR。

独立测试：`python -m pytest src/engineering_rag/modules/document_parser/tests -q`。
