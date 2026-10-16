# Document Parser 模块接口

> 状态：实现可用；输出契约为 **Document Schema V2.4 FROZEN**。跨模块代码只应依赖
> `engineering_rag.contracts` 中的 Protocol 和 Schema，不应导入本模块的 `internal/`。

## 1. 模块职责

Document Parser 把工程规范 PDF 转换为可追溯的 `Document`：

- 读取 PDF、校验来源身份并取得物理页尺寸；
- 从 PDF 文字层或中文 OCR 生成带 bbox 和阅读顺序的 `PageBlock`；
- 可选调用本地 MinerU 4.x，恢复标题、正文、表格、公式和图片候选；
- 可选建立页面类型、Section、正文 Clause、条文说明 Clause 及内容引用；
- 保留页码、Block、表格片段、公式和图片的来源关系；
- 对不完整、未核验或无法安全归属的内容保持 partial/unverified，不编造结果。

本模块不负责 Chunking、索引写入、检索、Embedding、Rerank、查询改写或 LLM 生成；
Parser 不主动调用其他业务模块。`is_mandatory` 也不会仅凭“应/必须”等措辞自动判定。

## 2. 稳定公共接口

唯一跨模块能力协议定义在 `engineering_rag.contracts.protocols`：

```python
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...
```

推荐的依赖方式：

```python
from engineering_rag.contracts.documents import Document, ParseRequest
from engineering_rag.contracts.protocols import DocumentParser


def ingest(parser: DocumentParser, request: ParseRequest) -> Document:
    return parser.parse(request)
```

组合根可使用模块工厂创建当前实现：

```python
from engineering_rag.modules.document_parser.api import create_document_parser

parser = create_document_parser(file_store)
```

公共路径如下：

| 路径 | 用途 | 稳定性 |
| --- | --- | --- |
| `engineering_rag.contracts.protocols.DocumentParser` | 跨模块依赖注入 | 公共契约 |
| `engineering_rag.contracts.documents.ParseRequest` | 解析请求 | 公共契约 |
| `engineering_rag.contracts.documents.Document` | 解析结果 | V2.4 Frozen |
| `engineering_rag.modules.document_parser.api.create_document_parser` | 当前实现的组合工厂 | 模块公开 API |
| `engineering_rag.modules.document_parser.api.PyMuPdfDocumentParser` | 当前具体实现 | 可替换实现；业务模块不应据此耦合 |

`internal/` 下的 MinerU DTO、Sidecar、语义装配器和 E2E 模型都是私有实现，不能作为其他模块的类型契约。

## 3. 最小调用示例

### 3.1 基础文字层 / RapidOCR

```python
from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import ParseConfig, ParseRequest, StandardMetadata
from engineering_rag.modules.document_parser.api import create_document_parser

parser = create_document_parser(file_store, document_engine="baseline")
request = ParseRequest(
    source_file=FileRef(
        file_id="file-gb-demo",
        uri="filestore://standards/demo.pdf",
        mime_type="application/pdf",
        sha256="0" * 64,  # 应填写 FileStore 中真实的 SHA-256
        size_bytes=123456,
    ),
    supplied_standard=StandardMetadata(
        standard_name="演示工程标准",
        standard_code="DEMO 100-2026",
        edition="2026年版",
        language="zh-CN",
    ),
    config=ParseConfig(
        config_id="baseline-v1",
        options={
            "page_selection": "1-3,8",
            "on_page_error": "continue",
        },
    ),
)
document = parser.parse(request)
```

基础路径优先使用足够完整的 PDF 文字层；文字不足或 `force_ocr=True` 时，将页面渲染后交给
RapidOCR。该路径只生成 provisional `body` Block，不生成 Section、Clause、结构化表格或公式。

### 3.2 本地 MinerU 4.x 与语义结构

```python
from pathlib import Path

from engineering_rag.contracts.documents import ParseConfig, ParseRequest
from engineering_rag.modules.document_parser.api import create_document_parser

parser = create_document_parser(
    file_store,
    document_engine="mineru",
    mineru_executable=Path(".local/mineru-runtime/.venv/bin/mineru-kit"),
    mineru_home=Path(".local/mineru-runtime/state"),
)
request = ParseRequest(
    source_file=source_file,
    supplied_standard=standard,
    config=ParseConfig(
        config_id="mineru-semantic-v1",
        options={
            "document_engine": "mineru",
            "page_selection": "49-50",
            "engine_output_dir": "data/parser-runs/example",
            "mineru_bundle": True,
            "semantic_structure": True,
        },
    ),
)
document = parser.parse(request)
```

MinerU 必须在工厂参数和 `ParseConfig.options.document_engine` 中都显式选择：前者注入后端，
后者选择本次请求的执行路径。MinerU 在隔离环境中以本地子进程运行，不调用外部解析 API。

## 4. 输入契约

### 4.1 `ParseRequest`

| 字段 | 公共类型 | 当前实现语义 |
| --- | --- | --- |
| `source_file` | `FileRef` | 必填；由注入的 `FileStore.read()` 提供二进制流 |
| `supplied_standard` | `StandardMetadata \| None` | Schema 允许空，但当前实现要求必填，不从文件名猜测标准身份 |
| `config` | `ParseConfig \| None` | 可空；空值采用默认配置 |
| `trace` | `TraceContext \| None` | 契约预留；当前 Parser 尚未消费该字段 |

若 `FileRef.sha256` 或 `size_bytes` 有值，Parser 会在流式复制源文件时核对真实内容；不一致则失败。
物理页码从 1 开始，`page_selection` 也使用 PDF 物理页码。

### 4.2 `ParseConfig.options`

未知键、错误类型和越界值都会被拒绝。

| 选项 | 默认值 | 约束与作用 |
| --- | --- | --- |
| `page_selection` | `None`（等价于 `all`） | 字符串，如 `1,16,24`、`1-3,8` 或 `all` |
| `max_selected_pages` | `20` | 正整数；选择页数超过此值时拒绝执行 |
| `max_pdf_bytes` | `268435456` | 正整数；源 PDF 大小上限，两个引擎均适用 |
| `document_engine` | `baseline` | `baseline` 或 `mineru` |
| `dpi` | `200.0` | 72～400；baseline 页面渲染分辨率 |
| `ocr_backend` | `auto` | baseline 使用；须匹配注入的识别器，工厂当前支持 `rapidocr` |
| `force_ocr` | `False` | baseline 使用；忽略文字层并执行整页 OCR |
| `min_text_layer_chars` | `50` | baseline 使用；低于阈值时改用整页 OCR |
| `max_page_pixels` | `40000000` | baseline 使用；单页栅格像素上限 |
| `on_page_error` | `raise` | baseline 使用；`raise` 或 `continue` |
| `engine_timeout_seconds` | `900` | MinerU 子进程超时，正整数 |
| `engine_output_dir` | `None` | MinerU raw/log 输出目录；空值使用自动清理的临时目录 |
| `mineru_tier` | `basic` | `basic`、`standard` 或 `advanced` |
| `mineru_bundle` | `False` | 保存并安全解压 MinerU ZIP bundle |
| `semantic_structure` | `False` | MinerU 使用；启用 PageType、Section 和 Clause 装配 |
| `semantic_explanation_cover_page` | `None` | 已人工核验的条文说明封面物理页锚点，必须为正整数 |

默认会选择全部页面，但仍受 `max_selected_pages=20` 限制。大文档应由编排器分批调用，或者由维护者
明确提高限制；不要在普通请求中无界执行全本推理。

## 5. 当前两条执行路径

### 5.1 `baseline`

1. `FileStore.read()` 打开源流，并在受限临时目录中复制 PDF。
2. PyMuPDF 检查 PDF、密码保护、页数、CropBox、旋转和资源限制。
3. 每个选中页面优先读取原生文字层；文字不足时以指定 DPI 渲染并调用 RapidOCR。
4. OCR 像素 bbox 转为 `pdf_points/top_left`，Block 按几何位置形成确定性阅读顺序。
5. 返回包含全部物理页的 partial Document；未选页为 `not_processed` 且 `blocks=[]`。

该路径不会把文本猜成 Title、Table、Formula 或 Image，所有可用文本暂映射为未核验 Body。

### 5.2 `mineru`

1. 先用 PyMuPDF 校验和暂存源 PDF，再调用本地 `mineru-kit parse`。
2. 只接受 `docvortex.middle/2.0` 且 producer 为 MinerU 4.x 的 MiddleJson。
3. 将 normalized top-left bbox 映射为各页 PDF points，保留原物理页号和源 index。
4. 对 MinerU 候选执行保守的表格、公式、Figure 和文本映射。
5. `semantic_structure=True` 时，再建立 PageType、Section、Clause、ContentUnit 和 `plain_text` 缓存。
6. 返回只包含已选择/实际输出页面的 partial Document；因此不能假设
   `len(document.pages) == document.page_count`。

当前 MinerU 后处理能力：

| 对象 | 行为 |
| --- | --- |
| 文本与标题 | 三级条文号保持 Body；Title 还必须满足页面水平居中几何门槛；页脚印刷页码有证据时过滤 |
| 表格 | 安全解析 MinerU HTML；恢复 rowspan/colspan、多级表头、原始网格、数据行和连续编号表注 |
| 跨页表格 | 仅在物理页相邻、显式“续表”、表号一致且列结构相容时合并为一个 `LogicalTable` |
| 公式 | 为每式生成稳定 `formula_id`；保留 LaTeX、可靠印刷编号、适用条件和共享“式中”解释 |
| 跨页公式语义 | 可保守接续下一页符号说明和公式印刷注释；遇到新条文或证据不足即停止并保留诊断 |
| Figure | 优先使用 MinerU image/asset；按图题聚合多图片段和可证明属于图内的无编号表达式 |
| 语义结构 | 证据驱动地识别页面区域、章/节、跨页 Clause、分项、正文与条文说明关系 |

所有机器识别内容仍是 `unverified`。缺失 bbox、不安全资产、不能可靠归属的元素不会被伪造；公共
Document 中无法表达的证据留在 Parser 私有 Sidecar，E2E 工具会将其落盘。

## 6. 输出及下游消费规则

`Document` 同时提供物理视图和语义视图：

| 数据 | 权威用途 |
| --- | --- |
| `page_count` | 源 PDF 总物理页数，不等于本次返回的 `pages` 数量 |
| `pages[].blocks` | 页面布局、bbox、阅读顺序和物理来源 |
| `sections` | 正文/条文说明各自的章节树 |
| `clauses.normative` | 规范正文条文 |
| `clauses.explanations` | 条文说明；可靠时通过 `explains_clause_id` 指向正文条文 |
| `tables[]` | 逻辑表格的唯一权威表示；Page Table Block 只是物理片段引用 |
| Formula Block | `FormulaGroup`、独立 Equation、稳定公式 ID 和符号解释的权威表示 |
| Image Block | Figure caption、bbox 和 `ArtifactRef`；结构化图号/多资产证据目前仅在私有 Sidecar |
| `processing` | Parser 身份、partial 状态和公共 warnings |

下游模块必须遵守以下规则：

- 按 `page_number` 和 `reading_order` 排序，不依赖列表碰巧已有的顺序。
- bbox 单位固定为 PDF points，原点固定为左上；不要与 OCR 像素坐标混用。
- Clause 内容应按 `content_units.order` 读取，并通过 `source_block_ids`、`table_id`、
  `formula_ids`、`asset_id` 解引用，不复制出第二份权威内容。
- `clause_content.plain_text` 是由冻结的 `derive_clause_plain_text()` 生成的缓存；为 `None` 表示
  来源边界或依赖不完整，不能当成空条文。
- `is_mandatory=None` 表示未判定。只有可核验的 `mandatory_evidence` 才能支持强制性结论。
- `recognition_status=unverified`、`content_extraction_status=partially_transcribed` 和 warnings
  必须传递给评估、Chunking 或人工复核流程，不能静默提升为 verified。
- 每次持久化或跨进程传输前，可用
  `Document.model_validate_json(document.model_dump_json())` 做完整引用与 JSON 往返校验。

## 7. 错误与部分成功

当前公共 Protocol 没有单独的错误 Result，也没有冻结的 Parser 异常层级。跨模块调用方不应导入
`internal` 异常类；应把 `parse()` 抛出的配置、I/O、PDF、OCR、MinerU 或 Pydantic 异常视为本次
解析失败，并由编排器记录、重试或终止。

常见失败包括：

- `supplied_standard` 缺失、未知配置键、非法页码或超过资源限制；
- `FileStore.read()` 失败，或声明的 SHA-256/大小与实际源文件不一致；
- 空文件、非 PDF、损坏 PDF、加密 PDF；
- OCR 未安装、OCR bbox 越界或识别结果格式非法；
- MinerU 不可用、非 4.x、超时、非零退出、协议不兼容或 ZIP/路径不安全；
- 最终 V2.4 引用、ID、bbox、表格或 Clause 完整性校验失败。

只有 baseline 的 `on_page_error="continue"` 提供页级部分成功：失败页保留为 `not_processed`，
并写入 `processing.warnings`。MinerU 单次 `parse()` 当前是整批成功或抛异常；大任务的失败重试由
E2E 编排负责。

无论使用哪条路径，当前实现都返回：

```text
processing.partial = true
processing.is_complete_document_ocr = false
```

这表示输出可用于后续处理和人工复核，但不能声明整份标准已完整、准确识别。

## 8. 副作用、幂等性与并发

- `parse()` 只通过注入的 `FileStore.read()` 读取源文件，不写检索索引或调用其他业务模块。
- PDF 会复制到自动清理的临时目录；配置 `engine_output_dir` 时，MinerU raw、bundle 和日志会持久写入该目录。
- MinerU 通过无 shell 的本地子进程执行；导入模块或创建 Parser 时不会加载模型、联网或启动进程。
- Document/Block/Table/Formula/Clause ID 基于来源身份、标准版次和源锚点确定，不依赖 OCR 文本内容。
- 相同源文件、标准身份、引擎版本和配置应产生相同身份与顺序；OCR/模型版本变化仍可能改变识别内容。
- `PyMuPdfDocumentParser` 会更新 `last_diagnostics`、`last_mineru_result` 和
  `last_semantic_result`，同一实例不应并发执行多个 `parse()`；并发任务应使用独立实例。
- 这些 `last_*` 属性及 Sidecar 都不是公共跨模块契约，业务协作应以返回的 `Document` 为准。

## 9. 大文档 E2E 工具（非公共 API）

`scripts/run_document_parser_e2e.py` 用于本地评估和批次编排，不替代 `DocumentParser` Protocol。
它支持：

- `live_mineru`：真实本地 MinerU 推理；
- `replay_saved_raw`：重放可信的已保存 normalized 产物，不执行推理；
- `synthetic`：仅用于测试夹具；
- 最多 20 页/批的计划、来源一致性校验、Checkpoint、`--resume`、失败记录；
- `--show-progress` 按实际成功页数显示进度；
- 最终 Document、Sidecar、lineage、pending、Overlay、QA 和资源统计产物。

示例：

```bash
python scripts/run_document_parser_e2e.py \
  --mode live_mineru \
  --pdf standard.pdf \
  --pages 1-20 \
  --output data/parser-runs/example \
  --run-id example \
  --show-progress
```

未带 `--resume` 时既有运行目录不可覆盖；恢复时会重新核对来源、配置、模型签名和成功批次产物。
完整文档执行还要求维护者显式批准。其他业务模块不应读取 E2E 私有 Manifest 代替公共 `Document`。

## 10. 版本与兼容策略

- 持久化 Schema：`Document.schema_version == "2.4"`，状态为 **FROZEN**。
- 当前公共能力签名：`parse(ParseRequest) -> Document`。
- Parser 实现版本、MinerU 版本、Artifact 版本、标准 edition/revision 和 Document Schema 版本彼此独立。
- V2.4 的破坏性变更必须升级 Schema 版本并提供显式迁移；不得在 Parser Sidecar 中悄悄改变公共字段语义。
- `2.4-proposal` 或其他旧结构不能直接当作 V2.4 使用，必须经过迁移和重新校验。

## 11. 安装与测试

基础 PDF 能力：

```bash
python -m pip install -e '.[dev,parser]'
```

RapidOCR 能力：

```bash
python -m pip install -e '.[dev,parser-ocr]'
```

MinerU 使用独立环境及 `requirements/mineru-task1-2.lock`，不是主项目导入依赖。

模块独立测试：

```bash
python -m pytest src/engineering_rag/modules/document_parser/tests -q
```

保存真实产物回归测试：

```bash
ENGINEERING_RAG_RUN_REAL_MINERU=1 python -m pytest tests/integration -q
```

全仓校验：

```bash
python -m pytest -q
ruff check .
ruff format --check .
```
