# Python → C++ 迁移状态

## 全仓库当前状态（2026-11-02）

当前活动源码树已移除全部 Python 源文件和字节码，运行入口、核心模块和示例使用原生 C++/Qt/OCCT；根工程已完成干净全目标编译链接，最终统一 CTest **16/16 通过，0 失败，68.86 秒**。**这不等于原功能、用户行为或所有模型已按 1:1 完整迁移。** 下文保留的28个示例入口映射和52件模型审计，只证明对应范围的实现与实跑情况。

### 原文件归档

- 234个原 `.py` 文件及原 `README.md`、`ARCHITECTURE.md` 已保存到 `migration/python-original-2026-11-02.zip`，不再留在活动源码目录；当前根目录同名文档是原生版本。
- 归档 SHA-256：`D3951AF710D9FF157299F6BF0E5F3A3F3C34D3C993DC1E297AB8DC7C3140709F`（本次文档更新已重新核对）。
- 原文件路径、原接口名称和资源中的历史源文件哈希仅用于迁移映射与溯源；原生构建和审计不依赖解压或执行 Python。归档保留验收基准，删除旧源文件不能替代未实现行为的补齐。

### 当前原生模块映射

| 范围 | 当前原生实现 |
| --- | --- |
| 应用启动、GUI、MCP入口 | `main.cpp`、`genform_mcp.cpp`、`genform/bootstrap.*`；根 `CMakeLists.txt` 构建应用、核心、测试和示例 |
| 文档、特征、命令执行 | `genform/document.*`、`features.*`、`session.*`、`commands.json` |
| API、协议与MCP运行时 | `genform/api/server.*`、`wire.*`、`mcp_runtime.*` |
| 几何与制造领域逻辑 | `genform/domain/`：几何、草图编辑、材料/属性、标准件、工艺和检查 |
| 建模内核与几何文件读写 | `genform/kernel/`：特征建模、网格/查询、规则配对与proof、紧固件、Unicode文件路径helper |
| 装配、运动及紧固件分析 | 独立 `genform/assembly/Engine`，实现位于 `engine.*`、`geometry.cpp`、`motion.cpp`、`analysis.cpp`、`bom.cpp`、`fasteners.cpp` 等 |
| GUI控制、草图交互与仿真桥接 | `genform/controller/`：控制器、动作、设置、草图编辑、仿真桥接和GUI自测 |
| 视口、捕捉、图纸与界面资源 | `genform/view/`、`qml/`、`genform/assets/` |
| 示例与回归 | `examples/native/`、`examples/recipes/`、`tests/` 及模块自测；28入口详表与52件模型记录见下文 |

这里列出的是当前代码职责和原生落点，不是逐项行为等价性承诺；独立装配engine的支持不能被误写为kernel本身承担全部装配接口。

### 已报告的真实验证证据

以下记录来自实际原生子集验证及归档、移除旧源码后的最终根工程干净构建。

| 范围 | 已观察结果与边界 |
| --- | --- |
| 根工程 | 清理后全目标重编译链接成功；最终16项CTest全部通过，0失败，68.86秒；protocol内部42/42通过 |
| 迁移 / 领域 | migration 18/18通过；domain 1880条断言通过 |
| 草图 / 视口 / GUI | sketch 63通过；viewport 17通过；GUI 65通过且 `qmlwarning[]` |
| 文件读写 / 规则检查 | fileio 423通过，含Unicode路径helper；inspect 18通过，含已迁移的规则配对/proof |
| 装配 | 真实装配回归通过，包含新fasteners回归；不是仅编译或空桩验证 |
| 示例 | 28入口映射与资源审计、52/52件有效实体审计及已运行的示例自测保留如下；不代表28入口所有业务流程均完成验收 |

### 尚未完整迁移或未保证等价

- 手势和规则设置的完整用户行为、任意斜面工作流仍未完整迁移；已有GUI、草图或内核分支测试不覆盖这些完整交互。
- 取消正在运行的计算、独立进程隔离/watchdog尚未实现；没有内核磁盘增量缓存或通用构建checkpoint。示例方法B的专用日志/检查点不能替代这些能力，也不兼容原Python checkpoint的完整行为。
- UI操作、拓扑编号/归属、材料/逐特征颜色展示和性能均未保证与原实现完全等价；没有逐一验证每个几何分支及参数组合。
- SKYE仍缺4份外部STEP，车辆动态阶段及方法B等完整业务流程未全部实跑。52件有效BRep、原生链接成功或旧Python源文件已删除，都不能据此宣告完整迁移。

## 示例迁移范围（2026-11-02）

本节保留 `examples/` 子任务的实现、映射和验证记录，**不宣称全仓库功能迁移完成，也不宣称28个入口已全部端到端验收**。
原28个Python示例现已随全仓库原文件归档，不在活动树；原生入口和审计不依赖旧源文件，资源中的 SHA-256 仅为可选历史溯源。
示例子任务当时的修改范围为 `examples/`、`examples/CMakeLists.txt` 和本文件；当前全仓库原生整合状态以前节为准。

已实现28个原模块的原生入口：真正的 C++ 建模、JSON配方执行、几何查询、离散运动验证、参考模型导出、图像展示和方法B检查点。
主程序调用 `genform::Session::execute(command, QJsonObject)`、`Session::tools()`、`Session::builder`、`Document`、原生域及OCCT内核。
**父任务已实现真实 Document/Session 并完成根 `build/` 全工程链接；本轮两个示例目标也已在该真实核心上重新构建、链接和运行。**
没有编造 Session/Document 替身。52/52零件配方真实内核审计通过；圆周与圆柱比较自测已修正错误测试假设并实跑通过，最终根16项CTest也已全部通过。这不等于28个入口均已端到端验收。

### 文件与职责

| 新文件 | 职责 |
| --- | --- |
| `examples/native/main.cpp`、`runner.hpp`、`runner.cpp` | CLI、原模块分派、原子JSON、配方执行、材质/颜色、修复/工艺、单次发送原生TCP客户端、哈希及自测 |
| `examples/native/geometry.hpp` | OCCT实体读写、变换、有效性/体积/包围盒、布尔干涉、点实体分类、孔道材料相交测试 |
| `examples/native/verification.cpp` | 两种锁扣验证、双向有限曲面采样比较、比较器微型自测 |
| `examples/native/surfaces.cpp` | 从真实车身射线采样，玻璃/饰件/安全缝线建模及轮胎/制动盘/玻璃参数细化 |
| `examples/native/presentation.cpp` | 原生Viewport离屏渲染、开闭/爆炸/拔塞状态、近景和真实剖切、默认装配规则报告 |
| `examples/native/skye.cpp` | 原STEP复制与核验、3件复现/9件可编辑参考、STEP/STL、安装孔/内部参考孔道检查 |
| `examples/native/alternate.cpp` | 方法B半截面Bezier/镜像策略、引用重映射、颜色保留、原子预写日志和保守恢复 |
| `examples/native/kernel_audit.cpp` | 独立运行真实内核的52零件配方审计；不替代Session集成验收 |
| `examples/native/catalog.hpp` | 28个原模块的显式原生入口映射、共享资源加载与结构/引用/覆盖范围审计；不读取Python源文件 |
| `examples/recipes/catalog.json.qz.base64` | 数据资源，不含可执行Python；解码/解压后是JSON |
| `examples/native/build_examples.cmd` | 使用本机已观察到的Qt/MSVC/OCCT构建；支持环境变量覆盖，不安装软件 |

### 不是机械伪转换

固定建模命令由原脚本的函数/字面量，经AST选择后在捕获器中取出，保留实际数值、顺序、别名、颜色、材质及装配数据。
没有用regex把Python语法改写成C++，没有把原脚本作为运行时子进程，C++没有 `QProcess`/`system()` Python路径。
资源格式为：base64文本 → 4字节大端未压缩长度 + zlib → UTF-8 JSON；C++用 `fromBase64` 和 `qUncompress` 读取。
JSON schema=1，124314字节，含5组构建配方、52件、367条零件命令、151条固定车辆阶段命令、装配、修复补丁、工艺提案及28源文件哈希。
动态射线采样、插值、运动学、布尔检查、Bezier转换、日志和渲染均由C++实现，不是提前保存计算结果代替算法。
迁移期重新提取资源与已保存资源逐字节一致；该证据属于历史提取过程。新增临时提取器 `examples/native/extract_recipes.py` 已读取后删除，不作为交付内容或重建/测试前提。
原生审计验证28入口、5构建模块、52件/367命令、4阶段/10组/151命令、13装配，以及别名先定义、颜色引用、装配文件引用、4组修复和11组工艺提案。合法缺省特征名由Session处理，重复装配显示名不等于重复实例。可选历史哈希只验证字段格式与映射，不要求源文件存在或重新计算源哈希；自测覆盖移除全部历史哈希仍通过、缺失模块/悬空别名/缺失阶段必须拒绝。

## 构建与验证

### 本机已观察到的工具链

- Qt 6.9.1 MSVC2022 x64：`C:\Qt\6.9.1\msvc2022_64`。
- MSVC：`C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat`。
- CMake/Ninja：`C:\Qt\Tools\CMake_64\bin\cmake.exe`、`C:\Qt\Tools\Ninja\ninja.exe`。
- OCCT 7.9 C++ SDK：`C:\Users\administered\anaconda3\envs\slicing_software\Library`。这里只使用头文件、`.lib`和DLL，**不加载该环境的Python**。
- 脚本允许覆盖 `QT_ROOT`、`OCCT_ROOT`、`VCVARS`、`CMAKE_EXE`、`NINJA_EXE`。

```bat
rem 当前主集成构建；父任务已接入根CMake，本示例子任务不改根CMake
cmake --build build --target genform_examples genform_examples_kernel_audit --parallel 4
ctest --test-dir build -R "^examples_" --output-on-failure
rem 可选独立示例构建，不要与根build同时运行
examples\native\build_examples.cmd --objects-only
examples\native\build_examples.cmd
```

根构建现已实际链接完整核心和示例；standalone CMake保留为可选构建方式，只链接必要OCCT库，避免SDK默认Visualization模块的无关VTK导入依赖。
根CMake的 `add_subdirectory(examples)` 集成由父任务完成，不属于本示例子任务的修改。
运行时须让Qt/OCCT DLL目录在PATH中；默认 `QT_QPA_PLATFORM=offscreen`，无需启动Python GUI或MCP适配器。
配方路径编译为当前 `examples/` 绝对路径；若移动源码/发布目录，应重新配置或后续改为安装资源定位，不能只复制exe。

### 已完成的真实证据

1. 父任务已完成根工程整体编译链接；本轮在根 `build/` 单次顺序构建 `genform_examples`、`genform_examples_kernel_audit` 成功，链接的是真实核心而非替身。
2. `examples_native_self_test` 真实运行：64弦圆周为12.5613245295773，解析64边形周长为12.561324627819，128弦周长为12.5651089658636，精确圆周为12.5663706143592。域 `length()` 原本定义为采样折线长度，不能用1e-6误差去断言等于解析圆周；现保留1e-6容差核验解析多边形、增加采样收敛与圆primitive核验，并通过Document往返及Session圆柱体积测试。
3. 独立审计器真实执行52件原生建模、检查全部特征状态 `ok`、存在实体、BRep有效，**52通过/0失败**：

| 原构建模块 | 零件数 | 本次原生内核实跑 |
| --- | ---: | --- |
| `button_latch/build.py` | 7 | 7/7通过，含开闭两根螺旋弹簧 |
| `button_claw_latch/build.py` | 16 | 16/16通过，含5种角度弹簧 |
| `powder_pump/build.py` | 9 | 9/9通过 |
| `powder_pump/lance.py` | 6 | 6/6通过 |
| `powder_pump_fan/build.py` | 14 | 14/14通过 |

4. 迁移时原28个脚本SHA-256全部匹配、资源再提取逐字节匹配；现 `examples_recipe_audit` 实跑通过上述完整结构及映射审计，且移除全部历史哈希仍通过，不再依赖Python文件位置。
5. 本轮根构建 `examples_kernel_recipe_audit` CTest真实通过（最终复跑19.57秒，52通过/0失败），报告含 `resource_audit.python_sources_required=false`，没有执行Python运行时。
6. `examples_comparison_self_test` 实跑通过：原4×5中心UV采样最大距离实测0.379960832109028 mm，漏掉圆柱±X极值，不能保证大于0.4 mm。现保留原全部样本及 `>0.4` 断言，增加真实圆柱解析极值点，严格核验最大/极值距离0.5 mm（1e-6容差）、两端包围盒平移量、inside/outside各一个；原identity、内部到边界距离、BREP回读、报告和禁止覆盖输入核验继续保留。
7. 以前的Session/Document未定义符号和 `sketchPoint` 编译冲突已由父任务及相关代理完成整合，不再是当前阻塞；旧 `examples/.native-build/verification/main-link.log` 仅为历史诊断，不代表本轮根构建状态。

审计命令（不依赖Session实现，不伪装主程序验收）：

```bat
cmake --build build --target genform_examples_kernel_audit --parallel 4
build\examples\genform_examples_kernel_audit.exe all build\examples\verification\all-recipes-kernel.json
rem 也可以只跑一个模块/零件
build\examples\genform_examples_kernel_audit.exe powder_pump/build build\examples\verification\pump.json pump_body.gform
```

本轮证据JSON位于 `build/examples/verification/all-recipes-kernel.json`，每件保留特征状态、体积/面积/尺寸、valid、耗时及失败信息。旧独立构建证据位于 `examples/.native-build/verification/`，按 `examples/.gitignore` 排除。
第一次直接内核诊断有3件缺 `diameter`，原因是绕过命令层时没有填原 `genform/features.py` 的hole默认值；
审计器按已读取的原字段默认 `diameter=5, head_diameter=10, head_depth=5` 补齐后全部通过，公制规格仍由内核表覆盖。
原配方没有因此修改，主程序仍通过Session调用，由Session负责通用命令默认值。

CTest入口：`examples_recipe_audit`、`examples_native_self_test`、`examples_comparison_self_test`、`examples_journal_self_test`、`examples_kernel_recipe_audit`。
示例子任务当时执行 `ctest --test-dir build -R "^examples_" --output-on-failure`，五项示例测试全部通过（5/5，19.78秒），包括资源审计、两个几何自测、日志自测及52件内核审计。随后最终干净构建的根16项CTest也已全部通过；这仍不能推出28入口所有业务场景均等价。

## 28个原模块 → C++映射及输入输出

下表命令均为 `genform_examples <入口>` 后的参数；可带原 `examples/` 前缀或 `.py` 后缀。
`O`表示用户指定输出/现有可编辑零件目录，`A`表示源车辆 `.gform`，`S`表示原始SKYE STEP目录。
默认不覆盖仓库 `models/`：生成器必须明确 `--output`。修复命令会修改该指定目录的 `.gform`，请使用工作副本。
K=52件内核实跑中的构建器；C=原生实现已编译链接，但该入口全部业务场景尚待最终端到端验收；I=另需外部参考输入。已运行的微型自测见前节，不冒充完整业务场景通过。

| # | 原Python模块 | C++入口 / 实现 | 输入、行为、输出与验收状态 |
| ---: | --- | --- | --- |
| 1 | `build_skye2_replica.py` | `build_skye2_replica` → `skye.cpp` | `--source S --output O`；保留源STEP副本及哈希，3件gform/STEP、整机gform/STEP/STL、装配/爆炸gasm、verification.json；比对原整机包围盒/分体数/体积。C+I |
| 2 | `check_skye2_reference.py` | `check_skye2_reference` → `skye.cpp`/`presentation.cpp` | `O`或`--output O`；默认装配规则和每件 `check_design`，输出 `design_check_*.json`、`design_check_summary.json`。C+I |
| 3 | `complete_skye2_reference.py` | `complete_skye2_reference` → `skye.cpp` | `--source S --reference R --output O`；3源件加孔腔、可拆硅胶塞、连接器、4触点，共9件；整机及拆分/拔塞装配、STEP/STL、JSON/README。R可选，只复制存在的参考文件。C+I |
| 4 | `present_skye2_replica.py` | `present_skye2_replica` → `presentation.cpp` | `O [--inspect]`；装配/正投影/爆炸/近景/剖切/拔塞PNG及哈希记录；是离屏CAD展示，不伪造完整GUI截图。C+I |
| 5 | `verify_skye2_reference.py` | `verify_skye2_reference` → `skye.cpp` | `O`；真实导出STEP的432安装孔采样+640前孔道采样、材料相交、侧孔/对壁/塞柄/9处局部实体检查，STL外形和设计报告错误核对；`export_verification.json`。C+I |
| 6 | `button_claw_latch/build.py` | `button_claw_latch/build` → `runner.cpp`+配方 | `frame|mechanism|hardware|springs|assembly|show|all --output O`；16件及7种装配，springs默认40°，可 `--angle 0|10|20|30|40`；新增all一次生成全部。K+C |
| 7 | `button_claw_latch/processes.py` | `button_claw_latch/processes` → `runner.cpp` | `--output O`；缺失时添加frame铆钉头避让，再绑定原工艺/待报价说明，保存并设计检查；`part_check_*.json`。C |
| 8 | `button_claw_latch/repair.py` | `button_claw_latch/repair` → `runner.cpp` | `frame|pushrod|door_striker|link_rivet|check_all --output O`；按特征名修改指定参数，保留process；已有报告首次保存 `_before.json`；check_all不修改零件。C |
| 9 | `button_claw_latch/spring_ends.py` | `button_claw_latch/spring_ends` → `runner.cpp` | `[0 10 20 30 40] --output O`；补闭口磨平端、绑定原压簧外购说明、设计检查；省略角度时扩展为检查全部现有spring文件。C |
| 10 | `button_claw_latch/validate.py` | `button_claw_latch/validate` → `presentation.cpp` | `closed|middle|open --output O [--export]`；检查默认装配规则、隐藏盖板/紧固件、PNG，可导20实体STEP；state JSON。C |
| 11 | `button_claw_latch/verify.py` | `button_claw_latch/verify` → `verification.cpp` | `--output O`；16件单实体有效、5状态、10弹簧座接触、21刚体角度、37释放采样、闭合阻挡、开闭STEP20实体及哈希；verification.json。C |
| 12 | `button_latch/build.py` | `button_latch/build` → `runner.cpp`+配方 | `core|springs|assembly|show|all --output O`；7件、开/按/爆炸3装配；show展示原爆炸装配；all为新增便利入口。K+C |
| 13 | `button_latch/present.py` | `button_latch/present` → `presentation.cpp` | `--output O`；验证螺栓两端、弹簧起点与8mm位移，隐藏盖板/螺钉，开闭PNG和完整STEP，图像哈希不同；presentation.json。C |
| 14 | `button_latch/verify.py` | `button_latch/verify` → `verification.cpp` | `--output O`；7件有效、2状态干涉分类、9行程采样；允许原简化螺纹包络重叠，不忽略其它干涉；verification.json。C |
| 15 | `porsche_911/alternate.py` | `porsche_911/alternate` → `alternate.cpp` | `--source A [--output O]`预览；`--execute --new-document --output O [--batch-size 2..6]`建B；`--resume`校验恢复。输出策略、映射、检查点、method_b.gform；不覆盖A。C |
| 16 | `porsche_911/alternate_runtime.py` | `porsche_911/alternate_runtime` → `alternate.cpp`/`runner.cpp` | 原模块为运行时支持；原生入口跑原子预写/拒绝部分状态自测，实际日志由alternate使用，TCP单次发送由runner使用。C |
| 17 | `porsche_911/compare.py` | `porsche_911/compare` → `verification.cpp` | `[A B] --report P [--uv-grid U V|--samples-per-face N] [--classify] [--tolerance T]`；双向截面采样、到目标全部面的MIN距离、min/mean/RMS/p95/max、最坏点、体积差、失败JSON；`--self-test`微型几何。C |
| 18 | `porsche_911/details.py` | `porsche_911/details` → `runner.cpp`+配方 | `lamp left|right`、`bumpers`、`mirrors`或all；`--source A --output O`；保留尺寸/颜色、拒绝重复阶段、体积减少保护；更新porsche_911_992.gform。C |
| 19 | `porsche_911/fasteners.py` | `porsche_911/fasteners` → `runner.cpp`+配方 | `--source A --output O`；27条螺栓/座/轮心和牌照螺钉命令；更新车辆。C |
| 20 | `porsche_911/glazing.py` | `porsche_911/glazing` → `surfaces.cpp` | `sample --source A --output O`生成surface_samples.json；`windshield|rear_screen|door_window|quarter_window --source A --samples D --output O`生成框/玻璃/镜像。C |
| 21 | `porsche_911/mcp_client.py` | `porsche_911/mcp_client` → `runner.cpp` | `[tools|COMMAND] [--source A] [--arguments args.json]`本地Session；`--remote [--port 9631]`原生TCP单次请求，超时不重发；输出JSON。不启动Python MCP子进程。C |
| 22 | `porsche_911/panel_lines.py` | `porsche_911/panel_lines` → `surfaces.cpp` | `--source A --samples D --output O`；从trim_samples.json生成前/门槛/后门缝和机盖边缝，截面loft+镜像，更新车辆。C |
| 23 | `porsche_911/refine.py` | `porsche_911/refine` → `surfaces.cpp` | `tires|wheels|glazing|all --source A --samples D --output O`；原轮胎十点截面、制动盘厚度符号、轮盖五螺孔、原线性插值玻璃轮廓；更新车辆。C |
| 24 | `porsche_911/trim.py` | `porsche_911/trim` → `surfaces.cpp`/配方 | `sample`输出trim_samples.json；`seams|handles|vents|badges --source A --samples D --output O`；真实射线取样、门/机盖缝、把手/油盖、11站格栅、文字徽标。C |
| 25 | `porsche_911/wheels.py` | `porsche_911/wheels` → `runner.cpp`+配方 | `front|rear left|right --source A --output O`；每轮15条轴/轮胎/轮圈/盘/辐条/盖/卡钳命令；all按独立别名域顺序执行4轮。C |
| 26 | `powder_pump/build.py` | `powder_pump/build` → `runner.cpp`+配方 | `[part.gform ...] --output O [--force]`；9件含原材料和颜色，粉泵gasm保留连续旋转铰链/运动件索引；未指定件则全部。K+C |
| 27 | `powder_pump/lance.py` | `powder_pump/lance` → `runner.cpp`+配方 | `[part.gform ...] --output O [--force]`；6件、suction_lance.gasm，保留0..45°进气调节环铰链。K+C |
| 28 | `powder_pump_fan/build.py` | `powder_pump_fan/build` → `runner.cpp`+配方 | `[part.gform ...] --output O [--force]`；14件含原材质/颜色，powder_pump_fan.gasm保留翻板/配重组与-60..0°铰链。K+C |

### 原生运行流程（已链接，业务场景待最终验收）

```bat
set E=build\examples\genform_examples.exe
%E% --list
%E% --audit
%E% --self-test
%E% porsche_911/compare --self-test
%E% porsche_911/alternate_runtime

%E% button_latch/build all --output examples\.native-build\smoke\button
%E% button_latch/present --output examples\.native-build\smoke\button
%E% button_latch/verify --output examples\.native-build\smoke\button

%E% button_claw_latch/build all --output examples\.native-build\smoke\claw
%E% button_claw_latch/processes --output examples\.native-build\smoke\claw
%E% button_claw_latch/repair frame --output examples\.native-build\smoke\claw
%E% button_claw_latch/repair pushrod --output examples\.native-build\smoke\claw
%E% button_claw_latch/repair door_striker --output examples\.native-build\smoke\claw
%E% button_claw_latch/repair link_rivet --output examples\.native-build\smoke\claw
%E% button_claw_latch/validate open --export --output examples\.native-build\smoke\claw
%E% button_claw_latch/validate closed --export --output examples\.native-build\smoke\claw
%E% button_claw_latch/verify --output examples\.native-build\smoke\claw

%E% powder_pump/build --output examples\.native-build\smoke\pump
%E% powder_pump/lance --output examples\.native-build\smoke\pump
%E% powder_pump_fan/build --output examples\.native-build\smoke\fan
```

车辆增量阶段应使用**尚未含该阶段**的输入文件；仓库现有完整车辆可能已有同名特征，拒绝重复是预期保护而非自动删除。
默认源是 `models/porsche_911_992/porsche_911_992.gform`，请用 `--source`选择正确阶段。
连续阶段以上一步输出为下一步源；先sample再glazing/trim/panel_lines；refine需要已存在对应轮胎/轮圈/玻璃。
方法B先预览，再以新输出目录执行；检查点有不确定或部分执行时停止，不盲目重发，不复用Python旧日志。
比较报告必须在两个输入文件的目录树之外，不能覆盖源文件；默认每面36 UV点，单面UV预算上限10000。

SKYE示例额外要求S目录内4个实际供给文件：`SKYE2_主体_R20.step`、`SKYE2_底盖_R20.step`、`SKYE2_探头_R20.step`、`SKYE2_整机_R20.step`。
本次仓库未发现这4份外部STEP，**没有用虚构几何替代**。按 build/complete → check → verify → present 顺序运行。
3件原样复现与9件补充参考是不同模式；`verify_skye2_reference`要求后者的侧塞、连接器和孔道，不适用于只有3件的原样复现。

## 未完成及不能自动保证的内容

- **业务场景验收**：真实Document/Session和视图已整体链接，根16项CTest最终全部通过，涵盖命令、文件、几何及默认设计检查；28入口全场景仍未全部执行。52件内核通过不等于所有Session业务链路通过。方法B的计划参数由Document创建、执行经Session标准化，仍需核对二者默认字段一致性，不能放宽检查掩盖差异。
- **模型等价性尚未验收**：52件只证明原生配方生成有效实体，未逐件与原Python导出比对体积/拓扑/质量属性；车辆各动态阶段、方法B全量和所有渲染/运动报告仍须实跑。不能从有效BRep自动推出行为/模型等价。
- **默认零件设计检查**：主程序调用真实 `check_design`，不删规则、不滤警告、不把未实现检查报为通过。内核规则配对/proof已迁移且inspect 18项实跑通过，不再以“非空rules一律未迁移”描述现状；这仍不等于全部业务规则、设置交互和模型结果已与原实现逐项等价验收。
- **GUI展示差异**：原Python私有反射槽、窗口等待和完整应用窗口抓图改为原生离屏Viewport及直接几何状态核验。没有生成虚假的 `SKYE2_GenForm界面.png` 或设计检查面板截图。GUI 65项和viewport 17项实跑通过不代表原材料/逐特征颜色、所有UI交互和真实窗口展示已完全等价；仍须逐场景验收。
- **相机/报告兼容**：近景使用原区域、原生相机重新适配，拔塞等角不保证像素一致。`presentation.json`为带 `records`/`limitations` 的对象，不是原脚本数组；下游应读取records。图像不是连续动画。
- **参考来源与说明**：需提供真实SKYE源STEP和原参考资料；原详细中文审核/图纸说明尚未逐段迁移，现输出README和机器可读证据，参考参数明确标估算/推断，不能声称厂家原设计或密封/压力/寿命认证。
- **比较器差异**：实现有限UV/边界双向距离和真实几何微型自测，不实现Python/OCP缓存与其重启/缓存污染自测；显式 `--cache-dir`拒绝，不偷偷忽略。有限采样不是严格Hausdorff，也不宣告exact equivalence。
- **持久化边界**：新JSON采用QSaveFile原子替换。方法B源码/计划/检查点哈希与参数、颜色、rollback核验，不接受Python旧日志；最后保存之后若进程中断且日志未提交，会要求人工核验现有B而非覆盖。它不操纵用户当前UI文档。
- **装配边界**：原静态装配的旋转/平移、铰链元数据保留；本地几何帮助器对mirror/swing显式拒绝，避免错算自定义变换。装配报告调用原生默认contacts/connectivity、域BOM/材料/工艺/紧固件孤立检查；锁扣连续碰撞、真实螺纹啮合、柔性、载荷和生产公差仍无证书。运动只验证所列离散样本。
- **后续验收**：原28脚本已随234个原Python文件及原两份根文档完成归档，活动树无Python源码及字节码；最终根16项已通过。28入口完整业务烟测、安装/可搬移资源定位仍需进一步验收。资源结构和入口映射审计不依赖历史源文件，不能仅凭链接成功或删除Python宣告行为等价，归档仍是历史验收基准。
