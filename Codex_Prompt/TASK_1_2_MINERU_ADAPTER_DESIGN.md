# Task 1.2：MinerU 单引擎适配设计（保留 Document V2.4 FROZEN）

## 目标与实施顺序

目标是**先在独立环境中真实部署并运行 MinerU，接着才基于真实产物做工程 RAG 私有适配**。本阶段不做 PaddleOCR 或引擎优劣比较。

```text
真实 GB 50010 扫描 PDF
  → 本地 MinerU 4.x（隔离运行环境、模型权重及配置）
  → 原始 MiddleJson / ZIP / Markdown / 图片与日志
  → MinerU 4.x 私有归一化（保留原始输出和缺失信息）
  → bbox 转换、PDF 源页映射、诊断与可视化
  → V2.4 Private Adapter
  → Document V2.4 — FROZEN (partial)
```

## 部署结构

- 单独的 `.venv-mineru` 或本地独立容器；主项目不必安装 MinerU 的大依赖。
- 优先官方 **MinerU 4.x**；隔离安装后执行 `mineru version --json` 和 `mineru-kit parse --help`；记录真实 CLI 与具体版本。软件/模型具体版本固定入运行 Manifest。
- 先使用基础包 CPU/ONNX 路线完成至少一页扫描 OCR；GPU 可用时可加速，但不是必须。首次模型下载可能耗时，要区分下载失败与解析失败。
- 访问外部仓库只用于下载依赖和模型，真实 PDF 永不自动发送到官方或第三方在线服务。
- 不能未经用户许可对全部 441 页进行高开销推理；只解析明确指定的页面及案例。

## MinerU 4.x 输出的几个容易踩坑的点

| 事项 | 4.x 规则 | 错误做法 |
|---|---|---|
| 无状态解析 | `mineru-kit parse` | 依赖 `mineru parse --json` 当完整结构输出 |
| 输出协议 | `schema="docvortex.middle"`、`schema_version="2.0"` | 解析成旧版 `pdf_info` / `_backend` |
| 页面索引 | MiddleJson `pages[].page_idx` 从 0 开始 | 在选页 PDF 上直接当原 PDF 页码 |
| 扫描件 | Standard 或其他支持 OCR 的档位，显式确认 OCR 方式 | 用 `flash --ocr-mode txt` 读取不存在的文字层 |
| 元数据 | `metadata.producer.version`、`extensions.mineru` 等 | 从固定单一字符串臆测模型版本 |
| 几何 | 当前协议可提供 `extensions.docvortex_layout` 的 PDF pt 尺寸与旋转信息 | 假定所有 bbox 是像素坐标或统一归一化坐标 |

**提醒：** 以上是当前 4.x 官方文档的协议建议，实际代码必须以安装版本的真实 JSON 和官方当次协议为准。对于其他大版本，新增私有协议适配，不静默重解释输出。

## 推荐内部目录（可以按现有代码组织调整）

```text
src/engineering_rag/modules/document_parser/internal/
  mineru/
    runner.py               # 本地 CLI 安全执行、版本检查与错误码
    protocol_v4.py          # 4.x JSON identity、page/block 解码
    models.py               # 仅本模块使用的可空数据类型
    normalizer.py           # 保存来源/顺序/图片/表格/公式候选及缺失字段
    bbox_mapper.py          # pt/px/旋转/选页映射
    v24_adapter.py          # 满足冻结 Schema 的 partial Document
    diagnostics.py          # 映射失败原因、置信度、warning
```

实现可只创建真正需要的文件；**不建议重建第二套公共 Schema 或复制完整 MinerU 依赖到主项目**。

## 输出分级与不可伪造约束

| 识别对象 | 本阶段最小做法 | 信息不足时 |
|---|---|---|
| Page | `page_number` 为原始物理页号、`page_type=unknown` | 保留 `not_processed`/partial |
| Title/Body | 有真实文本、阅读顺序、可转换 bbox 则创建 Block | 留在原始 sidecar 中并标注 unmapped |
| Table | 页面片段与顶层 LogicalTable 按相同 `table_id` 关联 | `structure_only` / `data=null`（需符合实际 V2.4 类型） |
| Formula | 公式组、`formula_id`、LaTeX、识别状态与来源 | `equation_number_status=unknown`，不造编号 |
| Image | 带真实图片资产和可信 bbox | 无图片时不造空资源 URL |
| Sections/Clauses | 目前保持空；Parser 领域逻辑下阶段再实现 | 不让通用标题/文本自动伪造 Clause |
| Text layer | 继续兼容已有 Task 1.1 处理路径 | 旋转/CropBox 缺陷不可绕过 |

## 独立脚本与验收

`scripts/mineru_env_check.py`、`scripts/prepare_mineru_eval_cases.py`、`scripts/run_mineru_cases.py`、`scripts/visualize_mineru_results.py`、`scripts/validate_mineru_outputs.py` 是推荐的私有工具命名，可按工程实际调整。

默认 pytest 不安装 MinerU，也不下载模型；真实测试必须显式启动。至少保证一页中文扫描 OCR **真实运行成功**、一个复杂表格/公式案例真实运行且留下 raw output、V2.4 的 partial 文档合法或说明具体无法转换原因。
