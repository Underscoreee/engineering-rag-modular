# Document Parser 接口（Document V2.4）

## 职责与非职责

未来 Parser 负责从源 PDF 识别物理页类型、Block、Section、正文/说明 Clause，以及跨页表格的逻辑聚合，输出合法 V2.4 `Document`。Task 0.1 没有 PDF/OCR、表格或公式识别实现。Parser 不调用 Chunking，不写检索索引。

## 公开路径与签名

`engineering_rag.modules.document_parser.api` 重导出 `engineering_rag.contracts.protocols.DocumentParser`：

```python
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...
```

`ParseRequest.source_file: FileRef` 必填；`supplied_standard`、`config`、`trace` 可空。返回 Document 须含 `schema_version="2.4"`、稳定 `document_id`、统一 bbox 坐标约定、`page_count`、页面、顶层表格、正文/说明 Clause 和 processing 状态。`source_file` 沿用 Task 0 的 `FileRef`。

## 校验、错误和部分成功

Pydantic 字段错误或悬空引用抛 `ValidationError`；未来实现对资源不存在、不支持格式及读取失败须明确报错，不得返回伪成功。部分输出设置 `processing.partial=true`；若 OCR 也未完成，则设置 `is_complete_document_ocr=false`。逐页标记提取状态；未处理页的空 blocks 不等于空白。未核实的表格/公式只保留可证实的片段、状态及警告，不填造数据或 LaTeX。

## 副作用、幂等、排序与依赖

`parse` 读取源文件，不写索引。相同源文件、配置和实现版本应可重复；ID 生成细节仍待 ADR 决定。Block 以本页 `reading_order`、Table fragment 以 `fragment_index`、Clause unit 以 `order` 稳定排序。实现仅依赖 contracts、自身 internal 和注入的 `FileStore` Protocol；导入 API 不接触外部服务。

## 接口示例与版本

```python
# 接口示例：parser 为未来注入实现，本仓库尚无业务实现。
document = parser.parse(parse_request)
```

Python API 版本 1；Document 持久化 Schema 为 **2.4**。旧版及 `2.4-proposal` 必须显式迁移和核验，破坏性变更另立版本和 ADR。

独立测试：`python -m pytest src/engineering_rag/modules/document_parser/tests -q`。
