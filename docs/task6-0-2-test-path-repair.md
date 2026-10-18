# Task 6.0.2：Parser 测试路径与回归基线

结论：**PASS**。本次只修改测试路径、辅助函数与本报告，不改变生产逻辑。

## 实际状态与原因

开始分支 main，已有 Task 6.0.1 未提交修改以及维护者移动案例文件的改动。
重新核实后，三个案例实际在根目录，Codex_Prompt/ 对应文件不存在。维护者在本轮明确确认
“按当前根目录位置修复”，因此本次没有恢复历史位置。移动来自任务开始前，未由本任务执行。

三个根目录文件与 HEAD:Codex_Prompt/ 下的历史内容逐字节相同，前后 SHA-256 一致：

| 文件 | SHA-256 |
| --- | --- |
| TASK_1_3_TEST_CASES.json | 1a5b86347cb91663df001d99033b5213ac45a752b0704ee10fd0435647068b22 |
| TASK_1_4_TEST_CASES.json | 160aadd47ccfe3fe76e444be98a4196f251ba9bcfcb69a94535dee9d9482dff0 |
| TASK_1_5_TEST_CASES.json | 71d938e4f45e0e992358844253b55b188169c4b1164d674d2866bcc4d69c3f01 |

由于维护者已移动文件，上一阶段 5 个收集错误本轮没有复现，修改前三个 Parser 文件已有
65 passed。本次消除它们对固定 parents[5] 的依赖，采用有仓库标志验证的稳定定位。
外部 cwd 复测还实际发现两个审计测试无法导入 scripts，另有保存 Document 的相对读取路径。
这些均已用测试辅助机制解决。

## 本次修改文件

- src/engineering_rag/modules/document_parser/tests/path_helpers.py：以 Path(__file__).resolve()
  向上检查 AGENTS.md、pyproject.toml、src/engineering_rag/__init__.py；读取维护者确认的
  根目录案例，没有其他目录 fallback。文件缺失时明确报出绝对路径。
- 同目录 test_table_reconstruction.py、test_formula_reconstruction.py、test_semantic_structure.py：
  统一调用定位函数；公式测试的 examples 路径复用同一根目录。
- 同目录 test_path_helpers.py：新增 5 项测试，覆盖三个实际案例的 cwd 独立性、案例缺失、
  仓库标志缺失；不生成任何案例 JSON。
- tests/audit/test_task15_independent_gaps.py：保存 Document 的读取路径从仓库根构造。
- tests/audit/conftest.py：从同一根目录定位 scripts 导入路径，pytest 结束时清理新增 sys.path 项。
- 本报告：记录实际位置、维护者确认、范围与运行证据。

test_task15_source_integrity.py 自身没有错误的数据路径，没有无关修改；外部 cwd 导入由
审计 conftest 处理。全局其他文件名引用是历史任务书/说明文字，不是文件读取。

## 按规定顺序执行的最终命令与结果

在项目根目录使用 .venv：

```bash
.venv/bin/python -m pytest src/engineering_rag/modules/document_parser/tests/test_table_reconstruction.py src/engineering_rag/modules/document_parser/tests/test_formula_reconstruction.py src/engineering_rag/modules/document_parser/tests/test_semantic_structure.py -q
.venv/bin/python -m pytest tests/audit/test_task15_independent_gaps.py tests/audit/test_task15_source_integrity.py -q
.venv/bin/python -m pytest src/engineering_rag/modules/document_parser/tests -q
.venv/bin/python -m pytest tests/contracts tests/architecture -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
git diff --check
```

| 检查 | 最终实际结果 |
| --- | --- |
| 三个 Parser 测试文件 | 65 passed |
| 两个审计测试文件 | 11 passed |
| Parser 全模块 | 170 passed |
| contracts + architecture | 184 passed |
| 完整 pytest | **497 passed，0 failed，24 skipped**；6.26 秒，无收集错误 |
| Ruff lint、format、git diff --check | 均通过 |

既有 24 项 skipped 的启用条件没有修改；未使用 skip、ignore、deselect 或放宽断言。
这些跳过不能计为真实外部集成通过。

## 其他工作目录验证

在 /tmp 使用项目虚拟环境 Python，对上述五个相关文件及 test_path_helpers.py 传入绝对路径
执行 python -m pytest ... -q：**81 passed**。没有设置 PYTHONPATH、复制案例或切回根目录。
首次外部 cwd 运行的两项 scripts ModuleNotFoundError 已由测试配置解决。

## 范围与剩余事项

本次没有移动、复制或修改原始案例/Golden 数据，没有改生产代码、Schema、Protocol 或
pyproject.toml，没有提交 Git。维护者已有的文件移动和 Task 6.0.1 修改均保留。
案例仍表现为 Codex_Prompt/ 删除、根目录未跟踪文件，由维护者决定提交方式。

完整回归基线已经恢复，没有待解决的测试失败。未进入 Task 6.1。
