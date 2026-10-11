# Document Schema V2.4 冻结验收表（模板）

> **当前状态：NOT VERIFIED**。本文件是交给 Codex 填写的验收模板，不表示实现已完成。
>
> 核查对象：全新模块化单体 Engineering RAG 项目的公共 `Document` 数据契约。

## A. 版本和 ADR

- [ ] 当前 schema_version 为正式 `2.4`，且从 `2.4-proposal` 的迁移/差异已记录。
- [ ] 如果已有正式发布 V2.4，已处理不兼容版本风险，没有静默破坏下游。
- [ ] ADR-001～007 已归档为 Adopted，实际模型、文档一致。
- [ ] Parser 实现选型和 Golden Dataset 未硬编码进公共契约。

## B. 数据模型

- [ ] PageType = 13 种类别 + `unknown`；BlockType = 5 种。
- [ ] `bbox_coordinate_system` 统一，页内 bbox 仅四坐标；页号从 1 开始。
- [ ] 顶层 `tables[]` 管理逻辑表格，`pages.blocks` 保留跨页物理片段，table_id 引用有效。
- [ ] `columns/data` 规范化模型存在；`raw_grid` 可空、支持多级/合并单元格、部分缺失。
- [ ] 表注为 `notes: null` 或 `[{number,content}]`；固定“注：”不拆作单独字段。
- [ ] 公式均有 `formula_id`；`equation_number` 可空，能区分确认无号和未识别。
- [ ] 正文与说明同号条文可共存，`clause_id` 唯一，说明关联可解析。
- [ ] ContentUnit 以引用为主，不重复权威正文/表格/公式；`plain_text` 是派生缓存。
- [ ] `is_mandatory` 三态 + `mandatory_evidence` 的已核验证据逻辑无冲突。
- [ ] 未完成 OCR 页面不会被判作空白；处理状态与引用一致。
- [ ] `sections.structure_path`、`processing`、Asset 版本等此前约定的字段未被擅自删除。

## C. ID、Artifact 与校验

- [ ] file/document/Artifact 身份作用域明确，解析快照不可覆盖。
- [ ] ID 唯一、Section 无环、所有 source_block/table/formula/clause 关联有效。
- [ ] `ArtifactManifest` 含版本、document JSON Ref、资源清单和 SHA256 等字段。
- [ ] 存储格式/版本迁移机制已规定但未声称实施真实后端。
- [ ] 原本已删除字段受到严格验证（不应被悄悄忽略或接受）。

## D. 示例与测试证据

| 检查命令 | 实际结果 | 日志/截图/输出位置 |
|---|---|---|
| `python -m pytest tests/contracts -q` | 未运行 | 待填写 |
| Parser 模块独立测试 | 未运行 | 待填写 |
| Chunking 模块独立测试 | 未运行 | 待填写 |
| `python -m pytest -q` | 未运行 | 待填写 |
| `ruff check .` | 未运行 | 待填写 |
| `ruff format --check .` | 未运行 | 待填写 |
| 合成完整/部分 Document JSON 往返 | 未运行 | 待填写 |
| Manifest JSON 往返 | 未运行 | 待填写 |
| ID / 引用非法反例 | 未运行 | 待填写 |

## E. 审核结论

- `ready_to_freeze`: **false（待验证）**
- 状态：`DRAFT / READY_FOR_REVIEW / FROZEN / BLOCKED` 之一，当前 `DRAFT`
- 阻塞事项：待填写
- 不兼容变更处理：待填写
- 维护者确认：待填写
- 最终冻结日期、提交 SHA / 标签：待填写

> 只有全部门槛已通过且维护者确认后，才可在文档中声明 **Document Schema V2.4 — Frozen**。协议正式冻结后，不兼容字段更改必须使用新版本及显式迁移策略。
