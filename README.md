# GenForm

GenForm 是面向人和 AI 协作的参数化三维建模软件。桌面界面、命令会话、几何内核、装配、领域计算、MCP 服务和示例入口现使用 **原生 C++20**；界面使用 **Qt / QML**，精确几何使用 **OpenCascade（OCCT）C++ SDK**。本机已完成 Qt 6.9.1、OCCT 7.9 与 MSVC 工具链下的完整编译链接。

**运行不需要 Python、PySide6、numpy、PyOpenGL 或 OCP Python 绑定。** QML、JSON 配方和模型是原生程序读取的数据，不是 Python 替代启动器。长度单位为毫米（mm），世界坐标系 Z 轴向上。

项目仍处于迁移验收阶段：原生可执行文件能够构建、运行，不代表旧实现的全部功能、交互和每条测试都已等价迁移。请同时阅读[当前限制](#当前限制)、[测试与验收状态](#测试与验收状态)、[架构说明](ARCHITECTURE.md)和[迁移记录](MIGRATION.md)。

## 快速开始：Windows / cmd

在项目根目录打开 **cmd.exe**：

```bat
build-native.cmd
run-native.cmd
```

打开已有文档：

```bat
run-native.cmd "C:\models\part.gform"
```

`build-native.cmd` 配置并构建根目录的 `build/`，输出桌面程序 `build\genform.exe` 和 MCP 程序 `build\genform_mcp.exe`；`run-native.cmd` 和 `run-mcp.cmd` 分别为两种入口设置 Qt / OCCT DLL 搜索路径并转交参数。这些脚本启动原生 EXE，不会启动 Python。

桌面的“GenForm（源码启动）”运行 `launch-from-source.cmd`，增量构建并启动 `build\window-native\genform.exe`，包含原生窗口命令及草图标注修复，避免覆盖仍在运行的旧 `build\genform.exe` 或 `build\ui-fix\genform.exe`。`build-native.cmd`、`run-native.cmd` 和源码启动脚本支持用 `GENFORM_BUILD_DIR` 指定构建目录；`run-mcp.cmd` 默认仍使用根 `build`。2026-11-02 的界面遗漏、已修复内容和待补功能见 [界面审计](migration/UI_AUDIT.md)。

### 工具链与 SDK

| 项目 | 要求或已验证环境 |
| --- | --- |
| 编译器 | 支持 C++20；本机为 Visual Studio 2022 MSVC x64 |
| CMake | 3.24 或更新 |
| 生成器 | 本机脚本使用 Ninja |
| Qt | CMake 最低声明 6.5；本机验证 6.9.1，MSVC x64 SDK |
| OCCT | 本机验证 7.9 C++ 头文件、导入库和运行时 DLL |
| 桌面 | 本机已验证 Windows；不据此宣称其他平台已经验收 |

Qt 需要 Core、Gui、Widgets、Qml、Quick、QuickControls2、Network、Concurrent、OpenGL、Svg 和 PrintSupport 模块。链接 Qt OpenGL 模块不表示三维视口沿用旧 OpenGL 引擎，见[当前限制](#当前限制)。

根脚本中的默认路径是**开发机配置**，不是所有用户必须安装到的位置。本机 OCCT SDK 取自一个 Anaconda 环境的 `Library` 目录，仅使用其中的 C++ 头文件、库和 DLL；**不需要激活该环境，也不运行其中的 Python**。其他来源的 ABI 兼容 OCCT SDK 同样可以通过路径配置使用。

在调用脚本前，用实际安装路径覆盖默认值；以下路径只是示例：

```bat
set "QT_ROOT=D:\SDK\Qt\6.9.1\msvc2022_64"
set "OCCT_ROOT=D:\SDK\OCCT-7.9"
set "VCVARS=D:\VS2022\VC\Auxiliary\Build\vcvars64.bat"
set "CMAKE_EXE=D:\Tools\CMake\bin\cmake.exe"
set "NINJA_EXE=D:\Tools\Ninja\ninja.exe"
build-native.cmd
```

`OCCT_ROOT` 应指向可找到 `include\opencascade`、`lib`、`bin` 的 SDK 前缀。Qt、OCCT、编译器的架构和运行库必须兼容。`build-native.cmd --test` 默认使用 `CMAKE_EXE` 同目录的 `ctest.exe`；如果 CTest 安装在其他位置，可另设 `CTEST_EXE` 覆盖，例如 `set "CTEST_EXE=D:\Tools\CMake\bin\ctest.exe"`。

### 通用 CMake 构建

已配置编译器环境，并让 `cmake`、`ninja` 可用时：

```bat
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="%QT_ROOT%" -DGENFORM_OCCT_ROOT="%OCCT_ROOT%"
cmake --build build --parallel 4
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
ctest --test-dir build --output-on-failure
build\genform.exe
```

也可让 CMake 通过 `find_package(OpenCASCADE)` 查找标准 SDK 配置，而不传 `GENFORM_OCCT_ROOT`。缺少 OCCT 时，部分文档/API 代码仍可构建，但几何命令会明确报告依赖错误；这不是完整 CAD 构建的替代验收。应用 QML、语言和图标已通过 Qt 资源系统打入原生程序，不再要求源码资源目录随行；Qt / OCCT DLL 与 Qt 插件仍需正确部署，示例配方也仍有源码路径依赖，因此不能仅复制一个 EXE 当作完整发布包。

## 桌面与建模

原生控制器接入现有 QML 窗口、设计树、参数面板、草图工具栏、装配树和工程图/仿真面板。主要能力如下；各项的范围和精度以实际命令、错误信息和覆盖记录为准。

| 模块 | 原生实现内容 |
| --- | --- |
| 草图 | 图形数据、交互编辑、捕捉、选择和二维几何编辑算法 |
| 参数化建模 | 特征历史、拉伸、旋转、扫描、放样、孔、圆角、倒角、阵列等 OCCT 建模路径 |
| 文档 | JSON 特征与属性、参数编辑、抑制、回滚、撤销/重做、保存/打开 |
| 视图 | 原生三角网格软件绘制、相机操作、拾取、选择、草图叠加、截图 |
| 装配 | 装配文档、零件位姿、关节/运动、干涉与分析、BOM 等 C++ 模块 |
| 领域功能 | 材料、制造工艺、成本、标准件、草图编辑与设计检查计算 |
| 文件与自动化 | `.gform`、装配数据、STEP/STL 几何交换、TCP 与 MCP 命令入口 |

最小零件流程：选择 XY 基准面，创建闭合矩形草图，完成草图后拉伸，检查设计树特征状态，保存 `.gform`。修改尺寸后重新计算；若出现错误，修正或撤销错误特征，不要将画面中的上一次成功实体误认为修改已成功。

`.gform` 是可读 JSON，保存特征参数及文档属性，几何由原生内核重建。STEP/STL 用于几何交换，不保存 GenForm 的完整参数化历史；需要继续编辑时同时保留原文档。导入特征和装配引用的外部文件也需要保留，移动项目时要检查路径。

## MCP 与本地命令

### 连接桌面

先启动 `run-native.cmd`，再在项目根目录的另一个 cmd 窗口中启动 MCP：

```bat
run-mcp.cmd
```

`run-mcp.cmd` 会设置 Qt / OCCT DLL 路径；如果 SDK 不在脚本默认位置，请为启动 MCP 的环境设置 `QT_ROOT` / `OCCT_ROOT`。推荐使用该入口，而不是在未配置 DLL 搜索路径的普通环境中直接启动 EXE。`run-native.cmd` 中的局部环境不会传给另一个终端。

MCP 默认将工具调用转发到 `127.0.0.1:9631` 的桌面会话，人可以看到同一份文档变化。根 `.mcp.json` 现在使用以下启动方式：

```json
{
  "mcpServers": {
    "genform": {
      "command": "cmd",
      "args": ["/d", "/c", "run-mcp.cmd"],
      "cwd": "."
    }
  }
}
```

这里的 `cwd: "."` 要求客户端以项目根目录为工作目录；若客户端从其他位置启动，请把 `cwd` 改为 GenForm 的实际绝对路径。按客户端规则传递自定义 SDK 环境变量，不要依赖其他终端的局部环境。

### 无桌面建模与协议检查

```bat
run-mcp.cmd --headless
run-mcp.cmd --help
```

`--headless` 使用本进程中的原生 `Session`，不连接桌面；视角、截图等依赖视口的工具不可用。它仍使用 Qt GUI 基础设施，但不会打开桌面主窗口。无显示服务的环境可按实际平台设置 `QT_QPA_PLATFORM=offscreen`，不能因此假定所有图形插件已打包。

MCP 使用 stdio 上**每行一个 JSON-RPC 对象**，协议输出与诊断输出隔离。下面是在 cmd 中发送初始化请求的最小检查，不代替完整 MCP 客户端握手：

```bat
echo {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"manual-check","version":"1"}}} | run-mcp.cmd --headless
```

实际工具清单通过 MCP `tools/list` 获取，执行使用 `tools/call`；不要将桌面 TCP 的 `cmd` 信封直接写到 MCP stdio。

### 本地 TCP

桌面服务仅绑定回环地址，默认端口 `9631`。设置 `GENFORM_PORT=9632` 可更换端口，设为 `0` 关闭桌面接口。MCP 同样读取该变量，还支持 `--port 9632` 显式覆盖。

TCP 使用换行分隔的 UTF-8 JSON 对象，例如：

```jsonl
{"cmd":"tools"}
{"cmd":"get_model","args":{"brief":true}}
{"cmd":"sketch","args":{"plane":"XY","shapes":[{"type":"circle","cx":0,"cy":0,"r":10}]}}
```

创建命令返回的特征 ID 可用于后续拉伸；以 `tools` 返回的参数 schema 为准。常用命令包括 `new_document`、`open_document`、`save_document`、`edit_feature`、`batch`、`get_model`、`list_edges` 和 `list_faces`。

**取消或超时不是内核已停止的证明。** 当前同步 OCCT 计算一旦开始，接口可报告取消/超时，但不能中断正在运行的计算。收到结果不确定的响应后先查询文档，必要时等待计算结束；不要自动重发修改命令。该版本没有旧式内核子进程 watchdog 或崩溃后自动恢复承诺。

## 原生示例

`examples/native/` 提供统一原生程序，映射原 28 个示例入口。入口名保留历史模块标识，但不执行历史脚本：

```bat
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
build\examples\genform_examples.exe --list
build\examples\genform_examples.exe --audit
build\examples\genform_examples.exe button_latch/build all --output build\example-output\button-latch
ctest --test-dir build -R "^examples_" --output-on-failure
```

配方生成、校验、比较和日志均有原生路径。输出通常要求显式 `--output`，不要指向唯一一份原始模型。各入口参数和证据见 [MIGRATION.md](MIGRATION.md)。

已完成 **52 个实际模型的原生内核审计，52 通过 / 0 失败**，包括 button_latch、button_claw_latch、powder_pump、lance 和 powder_pump_fan 配方；这不是 28 个入口全部业务流程已等价验收的证明。**SKYE 缺少 4 份源 STEP，车辆全流程没有完整实跑**，不得将缺资源或未执行的路径记为成功。

## 测试与验收状态

本机 cmd 快捷入口：

```bat
build-native.cmd --test
```

也可让对应的 `ctest` 在 PATH 中独立运行；构建脚本的测试入口支持上文所述 `CTEST_EXE` 覆盖：

```bat
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
ctest --test-dir build -N
ctest --test-dir build --output-on-failure
ctest --test-dir build -R "^(domain_tests|session_tests|migration_tests|protocol_tests|file_io_tests|assembly_tests|kernel_tests|inspect_tests|sketch_tests|viewport_tests|gui_smoke_test)$" --output-on-failure
ctest --test-dir build -R "^examples_" --output-on-failure
```

桌面冒烟也可使用 `run-native.cmd --gui-smoke-test`；无交互环境运行前可设置 `QT_QPA_PLATFORM=offscreen`。它验证原生控制器和 QML 的有限场景，不等于旧鼠标、手势和全部交互测试都迁移。

2026-11-02 最终干净构建与验证结果：

- 清理构建产物后完整重新编译、链接成功；执行 `build-native.cmd --test`，**16/16 项 CTest 全部通过，0 失败，总耗时 68.86 秒**。协议回归内部 42/42 组通过，真实 STEP 导出的 stdout 保持纯 JSON-RPC，OCCT 诊断保留在 stderr。
- 迁移回归的 4 个问题已从实现根因修复，现为 **18/18 组通过**；内核 inspect 的真实 rule-pair / proof 自测 **18 项通过**，中文及 emoji 文件 I/O **423 项通过**。
- GUI 冒烟 **65 项通过**，含中英语言和设置，`QMLWarnings=[]`；草图 **63 项**、视口 **17 项**、领域 **1880 项**自测通过。这些是各自子集的内部检查数量，不可与 CTest 数量相加。
- 示例子集 **5/5 通过**，其中真实模型审计 **52/52 通过**；SKYE 和车辆的未验证边界仍保留。原 62 项测试语义的部分/未覆盖情况继续由 [tests/COVERAGE.md](tests/COVERAGE.md) 追踪。

活动树中 `.py`、`.pyw`、`.pyc` 文件计数均为 0；原 234 份 Python 源码已逐文件校验归档。测试通过只代表当前原生套件，不意味着所有原功能和旧测试语义均已逐项等价迁移；完整限制仍以覆盖台账为准。

## 当前限制

- **同步内核与恢复边界：** 几何计算仍可能阻塞会话/界面；无法强制中断已开始的 OCCT 请求。不再使用旧进程 watchdog，也没有增量磁盘 checkpoint 或未保存工作自动恢复保证。内存撤销快照与原子保存不是崩溃恢复系统。
- **软件视口不是旧 OpenGL 引擎：** 当前原生视口通过 `QQuickPaintedItem` / `QPainter` 绘制三角网格。显示、遮挡、透明、拾取和性能不能宣称与旧渲染器完全等价；屏幕轮廓不代表精确隐藏线结果。
- **草图与参考几何：** 没有持续约束求解；任意斜平面草图和相关坐标变换/交互不应视为已全面等价。一次性编辑不等于关联驱动约束。
- **交互与设置：** 旧手势及设计规则设置尚未迁移；中英语言和已实现设置的冒烟通过不代表全部旧设置项已等价。
- **工程图与交换：** 精确隐藏线、DXF 及完整工程图输出链路尚非旧版完全等价实现。仅列出 UI 或命令不代表对应格式已通过验收。
- **拓扑与特征：** 基于坐标/邻近匹配的边面引用在大改尺寸后可能失效。复杂布尔、曲面、阵列、包裹、真实螺纹等需逐案检查，不能承诺任意输入成功。
- **分析不是认证：** 装配运动、干涉、静力和制造估算的支持范围以原生实现及测试为准，不是通用约束求解器或工程认证；不沿用旧实现未重新验证的精度数字。
- **资源和发布：** 应用 QML、语言与图标已内嵌；外部 STEP、装配引用以及仍使用源码路径的示例配方需正确定位。SKYE 与车辆验证边界见上文，独立安装包及跨平台发布尚未完成验收。

## 项目结构与历史备份

```text
GenForm/
├── CMakeLists.txt             # C++20 核心、桌面、MCP、测试和示例
├── build-native.cmd          # 本机可覆盖路径的 MSVC/Ninja 构建入口
├── run-native.cmd            # DLL 路径与桌面启动入口
├── run-mcp.cmd               # DLL 路径与 MCP stdio 启动入口
├── main.cpp                  # 桌面启动器
├── genform_mcp.cpp           # 原生 MCP stdio 入口
├── genform/
│   ├── document.* / session.* # JSON 文档、历史、命令与重算
│   ├── features.* / commands.json
│   ├── controller/           # QML 桥接与草图交互
│   ├── domain/               # 几何、材料、工艺、成本和检查
│   ├── kernel/               # OCCT 几何及显示数据
│   ├── assembly/             # 装配、运动、分析和 BOM
│   ├── api/                  # 回环 TCP、MCP 与协议编码
│   └── view/                 # 软件三角网格视口与图纸视图
├── qml/                      # 编入 Qt 资源的窗口与界面源文件
├── examples/                 # 原生入口、配方与审计
├── models/                   # 示例文档及外部几何资源
├── tests/                    # C++ 测试与 COVERAGE.md 迁移台账
└── migration/                # 旧源码和原文档的历史 ZIP 备份
```

原 **234 个 Python 文件及原 README / ARCHITECTURE 已归档**到 `migration/python-original-2026-11-02.zip`，各分组哈希已验证；活动代码树中的全部 `.py` 已通过补丁删除。ZIP 的 SHA-256 为：

```text
D3951AF710D9FF157299F6BF0E5F3A3F3C34D3C993DC1E297AB8DC7C3140709F
```

ZIP 仅为历史备份，不参与配置、构建、测试或运行，也不需要解压才能使用原生程序。更详细的职责与安全边界见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 故障检查

| 现象 | 检查与处理 |
| --- | --- |
| 找不到 Qt / OCCT DLL | 核对 SDK 架构及路径，桌面使用 `run-native.cmd`、MCP 使用 `run-mcp.cmd`；不要尝试安装 Python 包修复原生链接问题 |
| CMake 找不到 SDK | 检查 `QT_ROOT`、`GENFORM_OCCT_ROOT` 和实际头库目录；换编译器/SDK 后使用新的构建目录 |
| 找不到 `qml/Main.qml` | 正常构建已内嵌 QML；确认使用最新产物及资源构建成功。开发时可用 `GENFORM_QML_DIR` 指定包含 `Main.qml` 的覆盖目录 |
| MCP 无法连接桌面 | 确认窗口已运行、端口一致且未设为 0；独立建模改用 `--headless` |
| 无界面命令不能截图 | 截图/视角依赖实际桌面视口，使用连接桌面的 MCP 模式 |
| 超时或取消后结果不明 | 等待并查询当前文档，避免盲目重试修改命令；超时不保证回滚或计算中断 |
| 特征失败或体积异常 | 检查特征状态、闭合轮廓、引用和尺度；修正/撤销后重算并核验实体 |
