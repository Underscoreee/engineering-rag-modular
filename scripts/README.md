# Scripts

Task 1.2 提供以下有界、本地 MinerU 工具：

- `mineru_env_check.py`：记录主机、MinerU、模型与命令帮助。
- `prepare_mineru_eval_cases.py`：只渲染案例清单声明的页面。
- `run_mineru_cases.py`：运行显式案例/模式，支持超时、重试与 dry-run。
- `visualize_mineru_results.py`：把归一化 bbox 叠加到原 PDF 页。
- `validate_mineru_outputs.py`：用私有模型和冻结 Document V2.4 回读产物。
- `assemble_mineru_tables.py`：只重放已保存 raw，恢复格网并保守合并指定续表案例。
- `assemble_mineru_formulas.py`：只重放三组显式公式页，输出公式 sidecar、V2.4、overlay 与诊断。
- `assemble_mineru_clauses.py`：重放已保存产物，构建章节、条文、来源 lineage 和 pending。
- `run_document_parser_e2e.py`：Task 1.6 的 live/replay/synthetic 分离入口，提供有界批次、严格合并、checkpoint/resume、QA 与资源产物。

这些工具不会上传 PDF，也不会默认分析整份文档。Task 1.6 入口会拒绝未明确批准的全本运行。MinerU 使用独立环境；常规项目测试无需安装它。
