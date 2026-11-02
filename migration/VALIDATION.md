# 原生迁移验证记录

验证日期：2026-11-02，Windows x64；MSVC 19.38、Qt 6.9.1、OCCT 7.9、C++20。

## 最终命令与结果

1. 核对活动树 `.py/.pyw/.pyc` 文件：0；原文件 ZIP SHA-256 与 `migration/README.md` 一致。
2. 清理构建产物：`cmake --build build --target clean`。
3. 全目标重新编译和测试：`build-native.cmd --test`。
4. 结果：**16/16 项 CTest 通过，0 失败，68.86 秒**。
5. `run-mcp.cmd --help` 返回 0；`git diff --check` 返回 0。

| CTest | 最终结果 |
| --- | --- |
| session_tests | PASS |
| migration_tests | PASS，内部18组 |
| protocol_tests | PASS，内部42组，真实TCP/MCP/STEP |
| file_io_tests | PASS，中文/emoji STEP/STL/BREP |
| assembly_tests | PASS，含真实紧固件检查 |
| kernel_tests | PASS |
| sketch_tests | PASS |
| viewport_tests | PASS |
| inspect_tests | PASS |
| gui_smoke_test | PASS，原QML界面及语言/设置 |
| domain_tests | PASS |
| examples_recipe_audit | PASS |
| examples_native_self_test | PASS |
| examples_comparison_self_test | PASS |
| examples_journal_self_test | PASS |
| examples_kernel_recipe_audit | PASS，52/52零件有效 |

构建仍有非致命 MSVC C4702 提示及可选 Vulkan 头缺失提示；未伪称零警告。当前程序使用软件三角网格视口，不依赖 Vulkan。

测试全部通过不证明旧版全部功能逐项等价：内核任务隔离/watchdog、磁盘checkpoint、完整手势/规则设置、部分草图/工程图交互仍有限制。旧测试语义逐文件对应关系见 `tests/COVERAGE.md`；SKYE外部STEP与车辆完整流程仍有未验收项，见 `MIGRATION.md`。
