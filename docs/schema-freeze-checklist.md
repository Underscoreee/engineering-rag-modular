# Document Schema V2.4 冻结验收表

> 核查日期：2026-10-11。状态：**READY_FOR_REVIEW**。自动化门槛已通过时 `ready_to_freeze=true`，但维护者尚未确认，因此本文件不声明 Frozen。

## A. 版本和 ADR

- [x] `schema_version` 固定为正式目标 `2.4`；`2.4-proposal` 与 Task 0.1 候选差异已记录。
- [x] 未发现正式发布/外部消费证据；不兼容候选变更已记录且要求显式迁移。
- [x] ADR-001～007 已标为 Adopted，代码、接口和文档一致。
- [x] PyMuPDF 方向和 Golden Dataset 原则只在 ADR，未硬编码公共契约或增加依赖。

## B. 数据模型

- [x] PageType 为 13 类 + unknown；BlockType 为 5 类；统一 bbox、1-based 页码。
- [x] 顶层 `tables[]` 管理逻辑表，Page Block 管理跨页片段并双向校验。
- [x] `columns/data` 与可空 `raw_grid` 共存；合并格、部分缺口、重叠和越界有正反测试。
- [x] `notes` 为 null 或 `{number,content}` 数组。
- [x] 所有 Equation 有唯一 `formula_id`；编号有 printed/confirmed_absent/unknown 三态。
- [x] 正文和说明同号可共存，Clause ID 唯一且说明目标可解析。
- [x] ContentUnit 只保存引用；plain_text 带 renderer 版本与来源摘要并可重算。
- [x] `is_mandatory` 三态与 verified evidence 逻辑、冲突诊断有正反测试。
- [x] 未完成 OCR、raw_grid=null、latex=null 和 pending evidence 均显式表达。
- [x] `structure_path`、processing、Asset 版本、page_count 与 ocr.text 保留。
- [x] 正文/说明 Clause 来源页分别限定为 body/explanation_body。
- [x] complete 页面拒绝未处理 Block/片段/公式，允许已识别但待审核的 unverified。
- [x] plain_text renderer v2 包含公式符号说明，并对同组部分引用去重。

## C. ID、Artifact 与校验

- [x] file/document/Artifact/快照内实体作用域明确，历史快照不可覆盖。
- [x] ID 唯一、Section 无环、Block/Table/Formula/Asset/Evidence/Clause 引用已校验。
- [x] `ArtifactManifest` 含版本、UTC 时间、document JSON、Assets、URI、SHA-256 和大小。
- [x] FileStore 不可变提交与 Migration Protocol 已定义，未实现真实后端/转换器。
- [x] 此前删除字段和 Task 0.1 ContentUnit 副本均被 strict validation 拒绝。
- [x] Manifest parser version 与 Document 对齐；双方声明的 Asset 摘要/大小一致。
- [x] 深层原地修改后的 Bundle 在提交前必须重新完整验证，边界已有测试和文档。

## D. 示例与测试证据

| 检查命令 | 实际结果 | 备注 |
|---|---|---|
| `.venv/bin/python -m pytest tests/contracts/test_freeze_gaps.py -q` | `6 passed in 0.22s` | 修复前已确认同文件 `6 failed` |
| `.venv/bin/python -m pytest tests/contracts -q` | `114 passed in 0.73s` | 完整/部分/Manifest 往返及正反例 |
| Parser 模块独立测试 | `1 passed` | 无 OCR/PDF 实现 |
| Chunking 模块独立测试 | `1 passed` | 无切分算法实现 |
| 其余五业务模块独立测试 | 各 `1 passed` | 仅既有 Protocol 骨架 |
| `.venv/bin/python -m pytest -q` | `127 passed in 0.79s` | 无 skip、xfail 或失败 |
| `.venv/bin/ruff check .` | 通过 | 无 lint 错误 |
| `.venv/bin/ruff format --check .` | `110 files already formatted` | 通过 |
| 完整/部分 Document 与 Manifest JSON 往返 | 通过 | `tests/contracts/test_examples.py` 等 |
| ID / 引用非法反例 | 通过 | duplicates、dangling refs、raw grid、evidence、cache |

环境没有全局 `python` 命令；任务书原始 `python -m pytest -q` 首次返回 `python: command not found`。项目 `.venv/bin/python` 为 Python 3.11.17 项目解释器，后续全部结果均明确使用该入口。该解释器也未内置 pip，故 `.venv/bin/python -m pip install -e '.[dev]'` 返回 `No module named pip`；经批准使用等价的 `uv pip install --python .venv/bin/python -e '.[dev]'` 成功安装 editable package，并按 pyproject 将 pytest 从 9.1.1 校准为 8.4.2。

## E. 审核结论

- `ready_to_freeze`: **true（等待维护者验收）**
- 状态：`READY_FOR_REVIEW`
- 自动化阻塞事项：独立评审提出的 3 项 P1、3 项 P2 已修复；无剩余自动化阻塞。
- 不兼容变更处理：Task 0.1 是未发布候选；差异和显式 Migration Protocol 已记录，未提供猜测式迁移器。
- 维护者确认：**待用户验收**
- 最终冻结日期、提交 SHA / 标签：**待维护者填写**

> 只有维护者确认后才可声明 **Document Schema V2.4 — Frozen**。之后的破坏性变更必须升级 Schema 并提供显式迁移方案。
