# Python → C++ 回归覆盖清单

## 范围与判定

核对日期：2026-11-02。原目录共有 **63 个 `tests/*.py` 文件，其中 `__init__.py` 无测试，实际测试/冒烟脚本为 62 个**。旧项目的 **234 个 Python 文件已全部归档至 `migration` 下的 ZIP，并从活动树删除**；下表保留原文件名，作为原 62 个测试/冒烟脚本的语义追溯，不代表这些脚本仍在活动树。本清单按文件追溯测试名称和断言语义，不按新旧测试个数换算覆盖率，不声称语言迁移完全等价。

- **完整**：该原文件的可观察断言语义均有明确原生断言；不要求 Python 对象身份和 C++ 值对象实现相同。
- **部分**：只有列出的行为存在原生断言；遗漏、改变的协议或失败中的回归单列说明。
- **未覆盖**：未找到对应语义断言。相邻实现、同名命令存在或显式“不支持”错误，不计成功覆盖。
- `__init__.py` 标为“完整（无用例）”只为清单闭合，不计功能覆盖。
- 这不是行覆盖率报告；本次没有执行 Python runtime，也没有为不存在的功能创建 skip/假成功用例。

原生入口缩写：

| 缩写 | 源码及入口 |
| --- | --- |
| M | `tests/migration_tests.cpp`：下表给出具体函数；`main` 使用 `QCoreApplication`，逐组报告异常，任一失败返回 1；无 QtTest。 |
| S | `tests/session_tests.cpp`：`catalogTests`、`batchTests`、`metadataTests`、`queryTests`。 |
| D | `tests/domain_tests.cpp`：`geometryTests`、`propertyTests`、`editingTests`、`standardPartTests`、`proofingBoundaryTests`、`assemblyTests`、`manufacturingTests`。 |
| A | `tests/assembly_tests.cpp`：`dataTests`、`modelFileTests`、`geometryTests`、`actualGeometryTests`；后两类需要 OCCT。该文件由其它任务维护，本清单只记录已读取的明确断言。 |
| K | `genform/kernel/native_selftest.cpp`：`main`，编译定义 `GENFORM_KERNEL_SELFTEST`；OCCT 分支为实几何体积/拓扑断言。 |
| E | `genform/controller/sketch_selftest.cpp`：原生编辑器操作/字段/捕捉断言，实际编译定义为 `GENFORM_GUI_SELFTEST`。 |
| V | `genform/controller/viewport_selftest.cpp`：实际 `QMouseEvent`、三工作平面、拖拽和软件图像导出，编译定义 `GENFORM_GUI_VIEWPORT_SELFTEST`。 |
| I | `tests/inspect_tests.cpp` + `genform/kernel/inspect_selftest.cpp`：真实 OCCT inspect rules-pair 与 proof 几何 selftest，编译定义 `GENFORM_INSPECT_SELFTEST`。 |
| G | `genform --gui-smoke-test`：实际 GUI/QML 冒烟入口，中英切换、设置、装配和工程图断言。 |
| P | `tests/protocol_tests.cpp`：真实 Session、TCP 与 QProcess MCP 协议回归，包含排队取消、运行中结果丢弃和 OCCT 导出 stdout 纯 JSON-RPC。 |
| F | `tests/file_io_tests.cpp`：真实文件 I/O 回归，包含中文/emoji 路径 STEP、STL、BREP 导出与读回。 |

首轮原生迁移集成的 16 项 CTest 曾全部通过（68.86 秒），但该结果没有覆盖所有真实界面操作。随后补充 8 个入口，`build/ui-fix` 中 24/24 通过。2026-11-02 针对原生窗口动画和草图标注反馈，再新增 `window_controls_tests` 并扩充选择回归；在独立 `build/window-native` 完整构建后，完整 **25/25 项 CTest 通过、0 失败、164.00 秒**。真实 Main.qml 选择套件 49/49，Windows 窗框 149 项通过；窗口按钮记录实际 HWND 上的 `SC_MAXIMIZE/SC_MINIMIZE/SC_RESTORE`，系统动画查询开启且未更改设置。该命令/状态结果不是逐帧动画目视证明；另已实际观察新版本草图不再残留画布 XY/XZ/YZ 标签。未运行 Python。以下逐文件映射仍是首轮历史语义追溯；新增行为由本节和 `migration/UI_AUDIT.md` 补充，不能据此推导原 62 个脚本已逐项等价。

| 新增入口 | 实际覆盖 |
| --- | --- |
| `form_ui_tests` | 真 Main.qml 点击圆角/倒角、类型字段、输入保留、多选、长表单确认和内核提交，68 项。 |
| `form_pick_tests` | 活动字段接收草图/路径/参考几何、免 Ctrl 切换、多选过滤、轴引用、仅顶点模式拾取，38 项。 |
| `manufacture_ui_tests` | 真原生检查、用户/文档规则优先级、持久化失败、材质/规则/修订失效、排队取消、真实红像素和工艺绑定，13 组。 |
| `assembly_ui_tests` | 树和真实视口互斥选择、空白/平面后 Delete 无操作、Ctrl 加选、运动副删除、撤销、重排、改名与打开返回。 |
| `display_regression_tests` | 真 OCCT 拾取、单面与整特征高亮区别、边 owner、两种线框错误标红、材质色、特征颜色和不透明度，9 组。 |
| `selection_ui_tests` | 三基准面选择、工具条、双击、空白、hover、Esc；扩充真实 QML 标签进出销毁/恢复及相机更新、旧浮条/选择/picking 状态清理、草图框放和草稿续画，49 个场景。 |
| `window_frame_tests` | Windows DWM 圆角策略、缩放、最小化与恢复前状态、工作区、DPI、运行期样式修复；Windows 11 原生平台 149 项通过。 |
| `window_controls_tests` | 真 Main.qml 最小化/最大化按钮点击，目标 HWND 收到原生 WM_SYSCOMMAND，最小化后恢复保持最大化/普通状态，DWM 属性及只读系统动画设置。 |
| `drawing_regression_tests` | 旧 linear/round 尺寸无损往返、同视图捕捉、移动/比例/隐藏关联、旧布局绝对坐标、坏数据安全。 |

## 63 文件逐项映射

| # | 原 Python 文件 | 状态 | 原生回归入口、已覆盖语义和明确缺口 |
| --- | --- | --- | --- |
| 1 | `__init__.py` | 完整（无用例） | 空测试包入口，无断言，不计功能覆盖。 |
| 2 | `smoke_features.py` | 部分 | K 的 shell、pattern、fill、参考几何；S/catalog；M/sessionGeometryRecoveryAndExport。缺原脚本整套 UI 预选/动态表单/接受取消流程。 |
| 3 | `smoke_gui.py` | 部分 | G 实际 GUI/QML 冒烟，中英切换、设置、装配和工程图；V 图像导出与鼠标事件；M/sessionGeometryRecoveryAndExport 实体/文件闭环。缺原真实 API 启动、各视图截图和退出完整脚本的逐项等价验证。 |
| 4 | `smoke_interactions.py` | 未覆盖 | 无原生回归验证装配打开不自动检查、清除检查不复活、隔离恢复、实际装配框选以及轨道运动保持显示样式的整套断言。 |
| 5 | `smoke_quit.py` | 未覆盖 | 无启动 GUI 后关闭进程/退出时序回归。 |
| 6 | `smoke_shortcut.py` | 未覆盖 | E 直接调用编辑器不等于系统按键快捷键路由；无对应快捷键端到端回归。 |
| 7 | `smoke_sketch.py` | 部分 | E 草图图元、阵列、修复、捕捉；V 实际点击和拖动；K 草图拉伸。缺快速草图、重入/取消和原 UI/API 全流程。 |
| 8 | `smoke_sketch2.py` | 部分 | E 多类图元、关系、阵列、字段；V 三平面鼠标输入。缺整套原 UI 脚本和相同最终模型断言。 |
| 9 | `smoke_ui.py` | 部分 | G 中英切换、设置、装配和工程图实际 GUI/QML 冒烟且无 QML 警告；V 原生鼠标画图及 PNG 尺寸；M 建模闭环。缺原窗口截屏、右键菜单、工具栏和表单事件端到端流程的完整复现。 |
| 10 | `test_actions.py` | 部分 | K 基本面/边与网格关联；G 设置 UI 冒烟。设置 UI 通过不等于持久化完整覆盖；仍缺快捷键冲突和持久设置、手势表、矩形点/线命中、BVH 与全三角扫描一致性回归。 |
| 11 | `test_api_cancellation.py` | 部分 | P 真实 Session/TCP 控制连接取消：排队取消不执行 mutation、运行中取消丢弃迟到结果；真实 QProcess MCP 取消/EOF。运行中同步工作仍可完成，不能声称已中止内核；持有内核进程终止/watchdog 等原契约仍未覆盖。 |
| 12 | `test_api_speed.py` | 部分 | M/sessionCommandContracts 全量/brief/单特征模型、rename 不重建、截图回调载荷；M/compactChangeReplies 已通过，验证新特征以外的旧 feature 不带 params 及 rename 压缩契约。P 有真实 TCP/MCP 传输，但不据此宣称共享连接/重连、不可达错误和批量响应压缩的全部原断言已覆盖。 |
| 13 | `test_asm_rules.py` | 部分 | D/assemblyTests 电偶腐蚀、紧固件、重复件、BOM 缺项、质量/偏心、运动问题；A 几何干涉/运动采样。尚未逐一复现原开盖碰撞构型和完整原断言。 |
| 14 | `test_asm_tools.py` | 部分 | D/standardPartTests 全目录尺寸/生成；A/geometryTests 中已有螺纹啮合、相位等断言；K 实建螺钉/攻丝孔。缺原装配选边配合、所有线/圆测量、分层合并和导线检测语义逐项验证。 |
| 15 | `test_assembly_live.py` | 部分 | A/geometryTests 对接触/干涉和缓存结果有断言。缺 live UI 开关、预算分批、磁盘 pair 重载、结果清除与隔离状态恢复。 |
| 16 | `test_assembly_motion.py` | 部分 | A/dataTests hinge 旋转、限位、嵌套运动/循环拒绝、参数与 mate；A 几何运动扫描。缺控制器动作/动画、移除部件重编号、panel 编辑、live 开姿态和视图网格同步。 |
| 17 | `test_assembly_pages.py` | 部分 | A 测量/装配文件数据；K 边顶点测量。缺 tab 可用性、布局草图 UI 保存、日志按钮只切换不自动检查。 |
| 18 | `test_assembly_parts.py` | 部分 | A 镜像变换、接触/距离/质量/网格与文件装配；M/billFilesAndCsv 标准/自制 BOM、镜像归并；M/materialsAppearanceAndProcesses 负价格拒绝。缺相同文件只建模一次的计数断言、全部透明颜色传播和原孤立链案例。 |
| 19 | `test_assembly_tree.py` | 部分 | A 查询多部件网格/变换。缺树选中高亮、隐藏/隔离、hover、拖拽、右键/删除、打开零件返回、进度卡片、拾取和基准面展开的大部分 UI 回归。 |
| 20 | `test_batch_atomic.py` | 部分 | M/sessionBatchHistoryAndAtomicity 校验/引用/未知参数失败、205 步失败恢复原 redo、编辑/抑制/删除/rollback 恢复和逐步 undo；M/sessionBatchGeometryFailureAndRepair 一次几何重建、保留失败特征和 undo/redo；S/batchTests 禁止命令原子性。M/emptyBatchIsANoop 已通过，空批次成功且保持原状态。缺注入任意 handler 异常及通知/延后调用次数的替身测试。 |
| 21 | `test_batch_import.py` | 部分 | A 的混合实体/网格、部分加载失败标记；M/importSourceRefreshAndRoundtrip 实体源文件读入/更新。缺拖放控制器独立 component 索引、单次 mesh query、批量追加/保存 placement 及草图编辑阻止导入。 |
| 22 | `test_boolean_integrity.py` | 部分 | M/booleanFailurePreservesPrefix 无效 cut/common 拒绝、保留前缀并 skip 后续；K 真实布尔/体积和失败前缀。缺原广泛故障注入、损坏统一面/体积结果、分离 fallback 边界和缓存容量验证。 |
| 23 | `test_box_selection.py` | 未覆盖 | V 仅点击草图图元，不等于装配框选。无原 crossing/window、近裁剪面、矩阵镜像、ctrl 累积、隐藏件、多选树路由的原生断言。 |
| 24 | `test_button_claw_latch.py` | 部分 | A/actualGeometryTests 实建仓库 latch housing/button、正体积与质量。缺整行程连杆长度/单调终点、陈旧 STEP 拒成功、导出错误传播与警告保存脚本回归。 |
| 25 | `test_button_latch_presentation.py` | 未覆盖 | 无等待视口确实到达 placement、旧弹簧/旧 bolt 不得就绪、陈旧导出判错的原生回归。 |
| 26 | `test_check_panel.py` | 未覆盖 | 无检查日志/红色树行、清除/迟到结果、stale 状态、文档切换取消、用户规则持久设置的 UI 回归；M 命令检查和 I rules/proof 几何回归已通过，但不能充当 panel 交互覆盖。 |
| 27 | `test_display_stability.py` | 未覆盖 | 无各 display style 在运动中 GL render pass、深度/边面策略不变及相机控件的原生断言。 |
| 28 | `test_document_metadata.py` | 完整 | M/documentMetadataRoundtrip：process/folder 两次存取、loadData 后源 JSON 变更隔离、legacy 无可选字段；M/expressionFeatureRoundtrip：保存/重开/解析公式后工艺和源表达式保留。Qt 隐式共享值对象用可观察隔离替代 Python 深拷贝身份检查。 |
| 29 | `test_documents.py` | 部分 | A/dataTests 装配数据和路径；A/geometryTests drawing 投影/测量；G 装配和工程图 GUI/QML 冒烟；M 文件往返/BOM。缺 Drawing A3/A4 排版/比例、智能尺寸点击、标题、gdrw 相对引用和 DXF 文本布局的完整回归。 |
| 30 | `test_evaluate.py` | 部分 | K 基本实体属性、边顶点测量、section/silhouette；A 精确干涉/距离/质量、静力位移/应力；D 材料/质量。缺原所有测量选择组合、完整截面/投影边界、网格求解质量和全部误差条件逐项验证。 |
| 31 | `test_extrude_ends.py` | 部分 | K mid-plane；M/sessionGeometryRecoveryAndExport 编辑/rollback。缺 through/vertex/face/body/倾斜面/gap/双向全部精确尺寸、旋转反向对称及动态字段/拾取表单语义。 |
| 32 | `test_feature_colors.py` | 部分 | M/materialsAppearanceAndProcesses 颜色、透明度独立修改和清除、错误原子性；K 基本网格面归属。缺多次布尔后的所有 owner/origin、样条 loft cut 的磁盘恢复和显示 tint 一致性。 |
| 33 | `test_features.py` | 部分 | S/catalogTests 全路由/37 特征表；K 实体/孔/螺纹/旋转/扫掠/loft/shell/draft/split/wrap/多类 pattern；M 基本会话修复。缺所有原参数变体/精确体积、完整参考曲线/helix/rib 和表单 create/edit 往返逐项测试。 |
| 34 | `test_hollow_ops.py` | 部分 | K 实几何 void/fill/pocket，体积变化和有效 body。缺原薄壁相交、口袋分层、无空腔/错误路径等所有 hollow 案例。 |
| 35 | `test_import.py` | 部分 | K STEP 导出/读入体积；M/importSourceRefreshAndRoundtrip 读入实体后继续 cut、源缺失报错；F 中文/emoji 路径 STEP/STL/BREP 真实文件往返。缺缺面缝合修复、多贴合实体逐个切割和原错误诊断的逐项等价验证。 |
| 36 | `test_import_cache.py` | 部分 | M/importSourceRefreshAndRoundtrip 同一 Kernel 更新源后重建、全新 Kernel 冷读、删除源不得缓存成功。缺磁盘 key 和仅 source/downstream key 改变、name 不失效的具体缓存断言。 |
| 37 | `test_inspect_connections.py` | 部分 | I 真实 OCCT rules-pair 回归已通过：桥接形成传递连接时抑制 gap，同时保留 touch/shallow，另有 pair_limit 等边界断言；带 rules 的 inspect 已接通。尚未逐项证明原 face-only/shallow/未检查 bridge 构型全部等价，不能据函数名认定完整覆盖。 |
| 38 | `test_kernel.py` | 部分 | K 空模型、实体拓扑/网格/质量、失败与 rollback；M/booleanFailurePreservesPrefix、profileNestingBoundaryRegressions。缺原全部几何图元、缓存/引用/错误细节逐项验证。 |
| 39 | `test_kernel_watchdog.py` | 未覆盖 | watchdog 仍未实现；无只终止 owned job、deadline 不随 progress 延长、卡死终止后可重建的原生回归。P 排队取消或运行中丢弃结果不等于终止同步内核工作，正常 build 完成也不计 watchdog 覆盖。 |
| 40 | `test_manufacturing.py` | 部分 | D/manufacturingTests、proofingBoundaryTests 工艺选择、成本/批量、manual/mirror、设计/试制问题；M/materialsAppearanceAndProcesses 命令输入和存储；M/manufacturingCommandIntegration 已通过真实 bind/check 管线；I 新增 18 项真实 rules-pair/proof 几何 selftest 已 CTest 通过。仍需原全部工艺/规则边界逐项等价验证，不以管线可用声称完整覆盖。 |
| 41 | `test_mcp_builder_client.py` | 部分 | P 真实 QProcess MCP 取消通知、迟到结果不污染 stdio，以及取消后下一 ping 请求成功。尚未逐项复现原客户端超时/键盘中断触发通知的全部契约。 |
| 42 | `test_mcp_cancellation.py` | 部分 | P 真实 Session/TCP/QProcess MCP 覆盖排队取消不改模型、运行中取消丢弃结果、迟到/重复输出检查及 EOF 取消待处理连接。尚未逐项证明原 deadline、断连 mutation 禁重试和 shutdown 解阻塞等全部契约；不等价于内核进程终止/watchdog。 |
| 43 | `test_params.py` | 部分 | M/expressionsAndValueIsolation 运算/函数/嵌套解析、变量表单解析、源值不变；M/expressionFeatureRoundtrip 几何公式/前向依赖/未知变量/循环/文件往返；A/dataTests 装配参数/mate。缺全局参数写回各 part 文件及控制器 mate 编辑完整工作流；C++ 不复刻 Python `is` 身份优化。 |
| 44 | `test_pattern_colors.py` | 部分 | M/materialsAppearanceAndProcesses 颜色/透明度互不丢失；K pattern 几何。缺复制面 seed origin、多级 mirror/pattern 色继承、glass 三角形排序及自交 profile 提示的原断言。 |
| 45 | `test_screenshot.py` | 部分 | V 实际软件 PNG 保存/宽高；M/sessionCommandContracts headless 错误与 callback payload。缺真实 API 图片 base64/缩略图/各视角/路径及相关渲染一致性完整验证。 |
| 46 | `test_session.py` | 部分 | M/sessionGeometryRecoveryAndExport 建模→失败保留→修复→undo/rollback→编辑→存取→STEP；M/sessionCommandContracts 错误无半截、full/brief 与选择失效；S/catalog；M/documentHistoryAndRollback id 不复用。缺原 chamfer 点选及所有 exact faces/中文错误文本一致性。 |
| 47 | `test_shell_void.py` | 部分 | K 开口/闭口 shell、void/fill；M 基本失败前缀。缺原 shell/void 组合空腔和异常边界全套精确体积回归。 |
| 48 | `test_silent_failures.py` | 部分 | M/profileNestingBoundaryRegressions 共边三矩形、内触边 notch 两位置、三层环；D/assemblyTests 标准件 orphan；M/booleanFailurePreservesPrefix。缺 clearance 恰等阈值和命令行检查与窗口一致的端到端回归。 |
| 49 | `test_sketch_hover.py` | 未覆盖 | 无 hover 图元长/角/孔径字符串、单位和状态正确性的原生断言。 |
| 50 | `test_sketch_more.py` | 部分 | D/editingTests 与 E 图元变换、延伸/圆角/偏移/关系/阵列/修复、捕捉过滤、多选；V 实际鼠标。缺原所有 handle/字段、chain/框选与每个边界条件逐一复现。 |
| 51 | `test_sketch_tools.py` | 部分 | E 多图元和工具字段、drag cancel、文本路径、阵列；D editing/geometry。缺原所有工具/快捷操作与 UI 描述、相同字段集合和完整 undo/preview 序列。 |
| 52 | `test_sketcher.py` | 部分 | E 草图绘制/编辑/捕捉；V XY/XZ/YZ 实际点击、drag、一次捕捉、PNG；D ray/plane 往返。缺原所有 rectangle edge/corner drag、line chain escape 阶梯和绘制状态标记精确断言。 |
| 53 | `test_start_page.py` | 未覆盖 | 无 recent 上限/清理/磁盘持久化、startPage/docKind 和 API 关闭开始页的原生行为断言。 |
| 54 | `test_stl_import.py` | 部分 | A/geometryTests STL approximate 网格/禁止精确干涉、缺文件与 partial 载荷；F 中文/emoji 路径 STL 真实导出/读回已通过。仍缺原 ASCII/BOM/multiple solid、法向/破损/非有限、cache invalidation、百万面无 BREP 全部断言的逐项等价验证。 |
| 55 | `test_store_checkpoints.py` | 未覆盖 | 磁盘 checkpoint 仍未实现；没有跨进程/重开磁盘 checkpoint、修改末步只重算一次或快构建不存 checkpoint 的原生断言。F 文件往返或重新从头建得正确不等于断点缓存恢复。 |
| 56 | `test_store_stamp.py` | 未覆盖 | 无原 Python source-stamp 失效清单或 C++ 等效构建/格式版本缓存失效回归。源码不再是 Python 不足以证明缓存 stamp 迁移完成。 |
| 57 | `test_sweep_closed.py` | 未覆盖 | K 的简单开放直线 sweep 不能代替闭合 seam 精确切线/方向、非法 seam 停止合并、反向 compound 成员单独定向及 mixed/surface 拒绝回归。 |
| 58 | `test_text_layout.py` | 未覆盖 | D/text_layout 的给定 advances 和 K 单字“A”可拉伸不是实际字体“WIW”不重叠、kerning/宽窄字及 cold/warm 字体缓存一致性原断言。 |
| 59 | `test_tree_folders.py` | 部分 | M/documentMetadataRoundtrip folder 归一化/存取；M/documentAtomicFailures 多目标失败原子性；M/sessionBatchHistoryAndAtomicity folder 引用/undo。缺树 folder hierarchy、展开状态、多选移动/取消和 controller 显示。 |
| 60 | `test_tree_follow.py` | 未覆盖 | 无接受新特征或重算后树自动滚动、选中同步、批处理不抢选择等原生 UI 回归。 |
| 61 | `test_tree_signal.py` | 未覆盖 | 无 treeChanged 仅内容改变发信号、重复 changed 不发以及树对象缓存的原生断言；M 只验证 Session progress，不能替代。 |
| 62 | `test_view.py` | 部分 | M/sessionCommandContracts view callback、M 实体编辑；K 拓扑/测量；V 鼠标草图；P 真实 QProcess MCP handshake/tools-call 与 Session/TCP 转发。缺原 camera ray/拾取最近 edge/face、plane 命中、隐藏面/块和表单拾取等完整回归，协议全链路不等于视图交互全覆盖。 |
| 63 | `test_volume_cache.py` | 未覆盖 | K/M 精确体积数值不等于积分调用次数/缓存复用。无 analytic/plain 与 spline/adaptive 路由、compound 有符号成员积分、unchanged faces 复用计数的原生回归。 |

## 新增 M 回归的实际验证

M 的早期独立构建利用根 `build` 中 `genform_session_tests` 的 Ninja 编译/链接参数，替换为 migration 对应源和输出路径，链接 `genform_core.lib` 与 Qt/OCCT；产物为 `build/genform_migration_tests.exe`。现在已由根 CMake 正式注册为 `migration_tests`，不再只有独立验证。本次仅更新 `tests/COVERAGE.md`，不修改任何源码、测试实现或 CMake，也不将既有执行记录描述为本次重新运行。

当前已执行结果：**M 的 18 组全部通过，且根 CTest 中 `migration_tests` 已通过**。早期 14 PASS、4 FAIL 已是历史结果；unknown kind、empty batch、compact reply、manufacturing 四项均已真正修复并通过原回归，不是 skip，也不是把“显式不支持”改计成功。

通过的组：

1. `documentMetadataRoundtrip`：可选/嵌套元数据、Unicode 文件、回滚位置、clean/history/serial、值隔离。
2. `documentHistoryAndRollback`：合并参数、重命名、抑制、撤销/重做、回滚中插入/删除、分支 id、clear。
3. `documentAtomicFailures`：八类无效数据、无效操作/多目标部分失败、坏 JSON/缺文件/存盘失败均不改原数据、path/revision/undo/redo，原文件仍可读。
4. `expressionsAndValueIsolation`：运算优先级、负 modulo、前缀科学计数、函数、递归 JSON、未知变量/非法函数/非有限/嵌套与长度边界、表单变量解析。
5. `sessionCommandContracts`：命令/类型/引用错误原子性、模型 full/brief/single、元数据不重建、删除选择清理、view/screenshot 回调。
6. `sessionBatchHistoryAndAtomicity`：短/长失败批次保存模型/selection/revision/redo，命名/位置/数组引用、成功批次逐步 undo。
7. `materialsAppearanceAndProcesses`：材料/密度/质量、颜色和透明度独立覆盖/清除、错误原子性、manual process/cost、rules。
8. `billFilesAndCsv`：真实文件描述、排除 sketch/suppressed 工艺成本、镜像 BOM 分组、数量/成本、CSV BOM/转义。
9. `expressionFeatureRoundtrip`：真实表达式几何、工艺文件往返、未知变量可修复、循环依赖状态/后续跳过。
10. `sessionGeometryRecoveryAndExport`：真实特征失败可修复、禁止导出失败文档前缀、suppression/undo/rollback、存取/STEP。
11. `importSourceRefreshAndRoundtrip`：真实 STEP 导出/冷读/热读刷新/继续切割，删除源后不复用成功模型。
12. `sessionBatchGeometryFailureAndRepair`：批次一次 build 保留三特征和失败 hint，undo/redo 重现失败。
13. `profileNestingBoundaryRegressions`：原 silent failures 的三类四个共边/嵌套构型精确体积。
14. `booleanFailurePreservesPrefix`：无效 cut/common 保留原体积并跳过后续，不向 inspect 泄漏失败 tool。
15. `unknownDocumentFeatureIsRejected`：未知 feature kind 被拒绝，不生成无 maker 特征。
16. `emptyBatchIsANoop`：空批次成功且不改变既有文档状态。
17. `compactChangeReplies`：新特征以外的旧 feature 不带 params，rename 响应遵守压缩契约。
18. `manufacturingCommandIntegration`：真实 `bind_processes`/检查命令接通 rules-pair/proof 管线并通过断言。

## 原四失败的修复结果

| 原失败回归 | 当前实际结果 | 对应原契约/修复语义 |
| --- | --- | --- |
| `unknownDocumentFeatureIsRejected` | 已修复，M/根 CTest 通过。 | 拒绝未知 kind，不再依赖未知类型 title fallback 误放行；保留原 `Document::add` 拒绝未知类型契约。 |
| `emptyBatchIsANoop` | 已修复，M/根 CTest 通过。 | 空批次成功且状态不变，满足原 `test_empty_batch_keeps_existing_no_op_semantics`，不再因 minItems/dispatch 拒绝空 steps。 |
| `compactChangeReplies` | 已修复，M/根 CTest 通过。 | 新 sketch 响应仅新特征保留 params，旧特征和 rename 响应遵守原压缩契约。 |
| `manufacturingCommandIntegration` | 已修复，M/根 CTest 通过；I 的 18 项真实几何 selftest 亦 CTest 通过。 | 非空 rules 的 inspect 已实现并接通真实 bind/check、规则对和 proof 管线；不是仅 D 合成 report 通过或“不支持即成功”。 |

## 已执行的原生验证记录

以下是已经执行的结果，不是计划、预告，也不是原 Python 语义完整等价或行覆盖率的证明：

| 入口 | 已执行结果与证据边界 |
| --- | --- |
| M / `migration_tests` | 18/18 组通过，根 CTest 中该项通过；原四失败均已修复。 |
| I / `inspect_tests` | 新增 18 项真实 OCCT rules-pair/proof selftest 已 CTest 通过；包含 gap/touch/shallow、连接、规则边界和真实 proof 几何，不以函数名代替断言。 |
| G / `gui_smoke_test` | 65 项通过，涵盖中英切换、设置、装配和工程图，含实际 QML 且无 QML 警告；不推导为所有原 UI 事件完整覆盖。 |
| E / `sketch_tests` | 63 项通过；实际宏为 `GENFORM_GUI_SELFTEST`。 |
| V / `viewport_tests` | 17 项通过。 |
| D / `domain_tests` | 1880 assertions 通过；不将 assertions 数量换算为原 Python 测试数。 |
| P / `protocol_tests` | 修正旧 `Write` 诊断断言后独立重跑 42/42 组通过；使用真实 Session、TCP、QProcess MCP，覆盖取消排队/运行中结果丢弃。真实 OCCT STEP export 的 stdout 每行均为 JSON-RPC，Transfer 诊断保留在 stderr；不是用假导出或删除诊断绕过断言。 |
| F / `file_io_tests` | 423 项通过，包含中文/emoji 路径 STEP/STL/BREP 真实导出与读回回归。 |
| 根 CTest 汇总 | 干净构建后最终16/16全部通过，0失败，68.86秒；活动树无Python源码及字节码。原测试语义缺口仍按本表保留。 |

**仍未实现/未覆盖的独立欠项**：watchdog 和磁盘 checkpoint 仍未实现；stamp 失效以及未逐项复现的装配/树/显示交互仍按上表保留缺口。P 已覆盖真实协议取消，但排队取消和运行中结果丢弃不等于终止持有的内核进程；M/F 文件往返不等于 checkpoint 恢复；正常完成或裸几何正确性也不能替代 watchdog、缓存或 UI 状态断言。
