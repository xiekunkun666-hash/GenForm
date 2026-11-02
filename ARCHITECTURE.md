# GenForm 原生架构

本文描述当前 **C++20 + Qt / QML + OCCT C++ SDK** 的实现，不是历史 Python 架构的保留说明。单位为毫米，世界坐标系 Z 轴向上。本机已完成 Qt 6.9.1、OCCT 7.9、MSVC x64 的完整原生编译链接；其他工具链和发布平台以实际验证为准。

源码迁移与行为等价是两回事：当前桌面、MCP、命令、领域、装配和示例具有真正的原生实现，但仍有不等价或未覆盖路径。公开操作与构建入口见 [README.md](README.md)，示例迁移证据见 [MIGRATION.md](MIGRATION.md)，旧测试语义的部分/未覆盖项见 [tests/COVERAGE.md](tests/COVERAGE.md)。

## 1. 进程与模块图

```text
桌面进程 genform
  main.cpp → bootstrap.cpp
      ├─ QApplication / QQmlApplicationEngine → qrc 内嵌 Main.qml
      │       ↕ Qt 属性、槽、信号
      │   controller::AppController / SketchEditor
      │       ├─ view::Viewport（QQuickPaintedItem / QPainter）
      │       └─ view::SheetView / 仿真与工程图桥接
      │
      ├─ api::ApiServer（回环 TCP，监听线程）
      │       └─排队到 Session 所在线程
      │
      └─ Session（命令与当前模型）
              ├─ features / commands.json（参数与工具目录）
              ├─ Document（JSON 数据、内存历史、存取）
              ├─ domain（纯数据几何、材料、制造、检查）
              ├─ assembly::Engine（装配、位姿、运动和分析）
              └─ kernel::Kernel（同步 OCCT 建模 / 查询 / 导出）

MCP 进程 genform_mcp
  stdin JSON-RPC → api::StdioRuntime → stdout JSON-RPC
      ├─默认：TCP → 已运行桌面的同一 Session
      └─--headless：本进程的 Session → 同步 Kernel

示例进程 genform_examples / genform_examples_kernel_audit
  原生入口 + JSON 配方 → Session / Kernel → 模型、导出和审计报告
```

这些程序都直接链接原生代码，没有通过 Python 子进程、绑定层或脚本启动器完成建模。Qt 的线程、MCP 进程与**独立内核进程**不是同一概念：当前内核在调用进程内同步执行，不再具备旧版内核子进程隔离及 watchdog 自动重启机制。

### 模块职责

| 模块 | 位置 | 当前责任与边界 |
| --- | --- | --- |
| 启动 | `main.cpp`、`genform/bootstrap.*` | 建立 QApplication、Session、控制器、TCP 服务，定位 QML，注册视图类型并载入窗口 |
| 界面控制 | `genform/controller/` | QML 属性/槽、文档与特征操作、草图编辑、模拟/工程图桥接及有限冒烟自测 |
| 命令定义 | `genform/features.*`、`genform/commands.json` | 特征参数、默认值、目录与参考几何；JSON 目录通过 Qt 资源编入核心 |
| 会话 | `genform/session.*` | 单份文档、当前几何模型、选择、命令分发、查询、批处理、重算和变化通知 |
| 文档 | `genform/document.*` | 特征顺序、回滚位置、属性、修订号、脏标记、内存撤销/重做、JSON 读写 |
| 领域 | `genform/domain/` | 二维/三维数学、草图编辑、材料属性、制造工艺/成本、检查与标准件数据 |
| 几何 | `genform/kernel/` | OCCT BRep 建模、布尔、曲面、螺纹、检查、导入导出、表达式与显示网格 |
| 装配 | `genform/assembly/` | 外部零件、装配位姿、关节/运动、几何/静力/其他分析、标准紧固件和 BOM |
| 接口 | `genform/api/` | 回环 TCP、stdio MCP、JSON 编码、请求状态、超时与取消响应 |
| 视图 | `genform/view/` | 软件绘制三角网格、相机、拾取、选择、捕捉和图纸显示；不是旧 OpenGL 渲染器 |
| 示例 | `examples/native/` 与配方资源 | 28 个历史入口标识的原生分发、建模、比较、日志和模型审计 |

QML 负责界面布局与呈现，C++ 控制器暴露属性和操作；不要绕过会话直接在视图里改 BRep 或随意修改特征列表。领域算法尽量保留可独立测试的纯数据边界；核心几何类型不直接暴露给 QML 或外部协议。

## 2. 命令与重算数据流

一次典型修改：

1. QML 操作或 API 请求提供命令名和 JSON 参数。
2. `Session::execute()` 进入统一命令分发，使用命令/特征定义处理参数并更新 `Document`。
3. 需要几何更新时，`Session::rebuild()` 调用同步 `Kernel::build()`，按特征顺序计算到当前回滚位置。
4. 内核返回模型摘要、特征状态和显示数据；Session 更新当前模型并发出变化/进度信号。
5. 控制器刷新设计树、参数面板与视口；协议适配器将结果编码为对应响应。

查询不应偷偷修改模型。视图命令通过 `Session::viewCommand` 桥接到桌面；无视口的 headless 会话应明确报告不可用，而非伪造截图成功。

建模错误必须保留可诊断的特征状态和原因，不以空几何、零体积或上次的成功图形冒充本次成功。支持的失败恢复路径包括修改参数、抑制、回滚和撤销；其具体原子性与批处理行为以迁移回归为准，不能因存在 `batch` 命令就宣称任意失败都会撤销全部副作用。

### 线程与阻塞

TCP 监听运行在独立线程，请求排队到 Session 所在线程执行。MCP 使用独立协议处理线程接收 stdio，headless 建模仍由其 Session 的同步内核完成。这有助于接口处理请求状态，但**没有把 OCCT 计算变成可抢占任务**。

正在运行的几何计算可能占用会话/界面线程。取消通知、断连和响应超时可以结束协议层等待或阻止尚未开始的请求，但不能强制停止已开始的内核操作；不确定结果应作为不确定结果返回。客户端必须先查询/核验状态，不可用自动重试修改来掩盖不确定性。

## 3. JSON 文档与历史

`.gform` 保存可重建的特征数据，不序列化内存里的 OCCT 对象。当前文档格式核心为：

```json
{
  "format": "genform-document",
  "version": 1,
  "serial": 2,
  "upto": null,
  "props": {},
  "features": [
    {
      "id": "f1",
      "type": "sketch",
      "name": "profile",
      "params": {
        "plane": "XY",
        "shapes": [{"type": "circle", "cx": 0, "cy": 0, "r": 10}]
      },
      "suppressed": false
    },
    {
      "id": "f2",
      "type": "extrude",
      "name": "body",
      "params": {"sketch": "f1", "distance": 20, "op": "add"},
      "suppressed": false
    }
  ]
}
```

- `features` 是有顺序的特征定义；`id` 用于后续引用，不能只靠显示名称建立依赖。
- `serial` 维护编号生成，`upto` 表示回滚位置，`props` 保存文档级属性；特征还可带工艺或文件夹信息。
- `path`、`dirty`、`revision` 及撤销/重做栈属于运行态，不是已持久化的恢复日志。
- 读入时验证格式、版本、特征结构、重复 ID 和回滚位置等，再接纳数据；保存通过 `QSaveFile` 写入并提交，降低覆盖过程中留下半份 JSON 的风险。
- `checkpoint()` 在 `Document` 中指**内存历史快照**，不是增量磁盘 checkpoint；不能据此承诺断电、进程崩溃或内核崩溃恢复未保存文档。

装配和示例还会读写自身的 JSON 文档/配方，外部零件、STEP 和其他资源路径仍是显式依赖。归档 `.gform` 本身不等于已嵌入所有外部几何。导入资源变化或丢失必须显式处理，不应沿用缓存假装成功。STEP/STL 是交换结果，不替代参数化文档。

## 4. API 与 MCP 协议

### 桌面 TCP

`api::ApiServer` 默认只监听 `127.0.0.1:9631`，使用换行分隔的 UTF-8 JSON 对象，不是 HTTP，也不是 MCP JSON-RPC。`GENFORM_PORT` 接受 0–65535；0 关闭桌面接口。

```jsonl
{"cmd":"tools"}
{"cmd":"get_model","args":{"brief":true},"request_id":"inspect-1"}
```

命令和参数 schema 以实时 `tools` 结果为准。传输层验证 `cmd`、`args`、`request_id` 等字段形状；当前单行请求上限常量为 **16 MiB**，默认回复时限常量为 **300 秒**。限制的存在不等于已实现通用配额、身份认证或远程多用户权限管理。

请求跟踪区分是否已开始执行。取消、超时或断连后的响应不能证明操作没有发生，尤其是写文件、导出和几何修改。不要将监听线程的计时器误解为可杀死内核任务的 watchdog。

### MCP stdio

`genform_mcp.cpp` 是独立原生入口，`api::StdioRuntime` 处理每行一个 JSON-RPC 对象，当前初始化响应使用协议版本 `2024-11-05`。支持初始化、工具列举与调用、ping 和取消相关通知等路径；协议 stdout 与诊断输出隔离，日志不得混入 JSON-RPC 流。Windows 推荐通过 `run-mcp.cmd` 启动，由它设置 Qt / OCCT DLL 路径，再把参数传给原生 EXE。

```text
run-mcp.cmd                  → 桌面 TCP 转发
run-mcp.cmd --port 9632      → 指定桌面端口
run-mcp.cmd --headless       → 本进程原生会话，无桌面视口
```

根 `.mcp.json` 使用 `cmd /d /c run-mcp.cmd`，`cwd` 为 `.`；这要求客户端的工作目录是项目根目录，否则应配置实际绝对目录。在普通环境中直接启动 `genform_mcp.exe` 可能缺少 SDK DLL，不能把已配置开发终端中的运行结果推及所有客户端环境。

客户端使用 `tools/list` 和 `tools/call`；桌面 TCP 的 `{"cmd":...}` 不可直接当作 MCP 请求。工具调用成功只表示该次请求按协议返回，业务成功仍要核验工具结果、特征状态和实际输出文件。截图等视口相关能力不可在无桌面会话中伪造。

### 安全约束

- 默认回环服务面向受信任本机客户端，**不是沙箱**。能调用工具的客户端可能修改模型、读取引用文件、保存或导出到当前进程有权限的位置。
- 不要随意改为公网监听或通过无认证转发暴露服务；MCP 配置和工程路径也不应包含不必要的秘密。
- 参数表达式由原生算术解析器求值，不执行 Python。解析器对长度、嵌套、除零、未知变量及非有限结果设检查；这不是对所有输入/几何操作的安全证明。
- 外部 JSON、模型、STEP、QML 和示例资源都属于输入边界。检查返回状态与路径，不使用覆盖原文件的“验证”替代独立输出。
- 超时后不盲目重试非幂等命令；原子保存保护单次文档写入，不保证跨多个输出文件的事务。

## 5. 几何、视口与误差

OCCT 负责精确 BRep 运算；显示数据由内核生成三角网格和边线，`view::Viewport` 继承 `QQuickPaintedItem`，通过 `QPainter` 完成原生软件绘制、投影、相机与选择叠加。Qt Quick 的合成后端以及 CMake 链接 `Qt6::OpenGL` 都不意味着应用复用了旧 OpenGL 视口引擎。

因此必须区分三类结果：

| 结果 | 用途 | 不应作出的推断 |
| --- | --- | --- |
| OCCT BRep 与有效性检查 | 建模、交换与几何核验 | 不能由“屏幕看起来正确”替代有效性/体积检查 |
| 三角网格、边线、拾取 | 交互显示与截图 | 不是精确隐藏线、精确接触或认证级测量结果 |
| 采样/分析数据 | 曲线比较、运动、静力/制造估算等 | 不保证采样覆盖所有极值，也不自动继承旧版精度 |

测试容差必须与算法一致。例如采样折线长度不等于解析圆周，UV 网格也不保证包含曲面极值；应分别核验解析已知量、采样收敛和 BRep 有效性。不要扩大容差或移除失败断言，只为制造绿色结果；采样与精确结果应在报告中清楚标注。

边面坐标/邻近引用仍存在拓扑稳定性边界。上游几何大变后应报告引用失败或要求重新选择，不应悄悄匹配到无关对象。任意斜平面、持续草图约束、精确隐藏线与 DXF 等路径尚未完成旧版逐项等价验收，不能由模块名或工具目录推出完整支持。

## 6. 构建、资源与部署

根 `CMakeLists.txt` 声明 C++20，构建 `genform_core` 静态库和 `genform`、`genform_mcp` 可执行文件；启用 CTest 时接入测试，根工程也接入原生示例。Qt 的 AUTOMOC / AUTORCC 生成桥接与资源代码，`commands.json`、应用 QML、语言和图标均通过 qrc 编入原生程序，桌面不再依赖源码资源目录。

Windows 快捷入口：

```bat
build-native.cmd
run-native.cmd
run-mcp.cmd --headless
```

构建脚本支持 `QT_ROOT`、`OCCT_ROOT`、`VCVARS`、`CMAKE_EXE`、`CTEST_EXE`、`NINJA_EXE` 覆盖；两个运行脚本使用 `QT_ROOT` / `OCCT_ROOT` 设置 DLL 路径。本机 OCCT SDK 位于 Anaconda 环境的 `Library` 目录，这是 SDK 文件来源，不是运行时 Python 依赖；其他兼容 SDK 前缀可替换，不应把开发机绝对路径写成所有人的要求。

通用配置示例（先准备编译器环境与对应工具的 PATH）：

```bat
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH="%QT_ROOT%" -DGENFORM_OCCT_ROOT="%OCCT_ROOT%"
cmake --build build --parallel 4
set "PATH=%QT_ROOT%\bin;%OCCT_ROOT%\bin;%PATH%"
ctest --test-dir build --output-on-failure
```

Qt / OCCT 的库、DLL、架构和运行库必须与编译器匹配。没有 OCCT 的降级构建会使几何命令报依赖错误，不可作为完整原生建模验收。`build-native.cmd --test` 默认从 `CMAKE_EXE` 所在目录推导 `ctest.exe`，也可显式设置 `CTEST_EXE`，不再固定到本机 Qt Tools 目录。

启动时 QML 优先检查开发覆盖目录 `GENFORM_QML_DIR`，然后查找内嵌 `:/genform/qml` / `:/qml`，之后才回退到 EXE 同级 `qml/`、相对 `share/genform/qml/` 和编译时源码目录。应用 QML、语言和图标已内嵌，不再要求源码目录存在；这不等于所有运行依赖均被静态打包。发布仍需部署 Qt / OCCT DLL 与 Qt 插件，定位外部模型；示例 recipes 仍使用源码路径，移动或单独发布示例有部署限制。当前不能只复制 EXE 就宣称可移植安装包已完成。

## 7. 测试与迁移证据

验收至少应分别记录：编译/链接、原生单元/会话/内核/装配测试、QML 冒烟、MCP 真实协议链路、示例入口，以及旧测试语义的覆盖情况。原生程序“有此命令”或测试“成功启动”都不能替代业务断言。

截至 2026-11-02 本轮文档更新时：

- 清理旧构建产物后完整重编译、链接成功；`build-native.cmd --test` 最终 **16/16 项 CTest 全部通过，0 失败，68.86 秒**。其中协议内部 **42/42 组通过**，保留真实 OCCT 导出、stderr 诊断和 stdout JSON-RPC 纯净性断言。
- 迁移回归的 4 个实现问题已根因修复，**18/18 组通过**；真实内核 rule-pair / proof 自测 **18 项通过**，中文及 emoji 文件 I/O **423 项通过**。
- GUI 冒烟 **65 项通过**，包括中英语言和已实现设置，`QMLWarnings=[]`；草图 **63 项**、视口 **17 项**、领域 **1880 项**自测通过。内部断言/检查数与 CTest 条目数是不同统计单位，不可相加。
- 示例子集 **5/5 通过**；真实内核审计 **52 个模型通过 / 0 失败**，含特征状态、实体存在和 BRep 有效性核验。
- 28 个示例入口已有原生映射/实现，但 **SKYE 缺 4 份源 STEP，车辆全流程未完整实跑**；52 件审计不能证明这些路径已通过。
- 原 62 项测试语义的部分覆盖、未覆盖和具体缺口继续由 `tests/COVERAGE.md` 追踪，不宣称旧测试已逐个等价迁移。最终构建前核对活动树无 `.py/.pyw/.pyc`，运行和测试不依赖归档 Python。

推荐复核命令：

```bat
ctest --test-dir build -N
ctest --test-dir build --output-on-failure
ctest --test-dir build -R "^examples_" --output-on-failure
run-native.cmd --gui-smoke-test
```

GUI 冒烟可在适合的平台设置 `QT_QPA_PLATFORM=offscreen`，但该模式不能替代真实桌面全部鼠标交互、性能与截图验收。迁移回归及协议、文件 I/O、inspect、草图、视口测试现已接入根 CTest；测试条目通过也不替代 `tests/COVERAGE.md` 中旧测试语义的逐项核对。

## 8. 当前结构与未完成边界

```text
GenForm/
├── CMakeLists.txt
├── build-native.cmd / run-native.cmd / run-mcp.cmd
├── main.cpp / genform_mcp.cpp
├── genform/
│   ├── bootstrap.*
│   ├── document.* / session.* / features.* / commands.json
│   ├── controller/           # AppController、SketchEditor 与界面桥接
│   ├── domain/               # 几何、属性、制造、检查、标准件
│   ├── kernel/               # OCCT、表达式、显示数据与几何运算
│   ├── assembly/             # 引擎、运动、分析、BOM、紧固件
│   ├── api/                  # server、wire、mcp_runtime
│   └── view/                 # viewport、sheet、sketch_snap
├── qml/                      # 编入 qrc 的桌面布局与组件源文件
├── examples/                 # 原生入口与 JSON 配方/验证资源
├── models/                   # 文档、装配与外部几何输入
├── tests/                    # C++ 测试、覆盖台账
└── migration/                # 已落盘的历史源码和原文档 ZIP
```

明确保留的技术缺口：

1. 可中断/隔离的长时间内核任务、旧进程 watchdog 等价机制及崩溃恢复尚未完成；当前没有增量磁盘 checkpoint。
2. 软件三角网格视口不是旧 OpenGL 渲染器等价移植；复杂遮挡、透明、性能和精确隐藏线不能混为一谈。
3. 任意斜平面草图、持续约束求解、拓扑命名稳定性和完整工程图/DXF 等仍有未等价或未覆盖项。
4. 旧手势和设计规则设置尚未迁移；语言及已实现设置的冒烟通过不代表全部旧设置项等价。
5. 领域/装配分析与制造检查应按真实支持范围报告，不承诺通用求解、商业 CAD 全功能等价或未重新测量的误差界。
6. 缺失输入、未实跑车辆流程、旧测试语义缺口、示例配方源码路径及独立部署验收都必须显式保留，不能记作通过。

原 234 个 Python 文件及原 README / ARCHITECTURE 已归档到 `migration/python-original-2026-11-02.zip`，各分组哈希已验证，活动代码树中的全部 `.py` 已通过补丁删除。归档 SHA-256：

```text
D3951AF710D9FF157299F6BF0E5F3A3F3C34D3C993DC1E297AB8DC7C3140709F
```

该 ZIP **只用于历史追溯，不参与原生构建、测试或运行，也不是回退到 Python 的运行机制**；当前文档只描述原生架构，不再把历史 worker/client、PySide6 混入类或 OpenGL 实现当作现行组件。运行原生程序不需要解压备份或安装 Python。
