# C++ GUI 遗漏审计与修复验收

## 当前验收状态（2026-11-02）

本报告后半部分保留修复前的静态发现作为追溯，包含当时的行号、未接通状态和待验收说明；它们不代表下面这些问题仍未修复。当前结论以本节及原生回归结果为准。旧实现仅通过 .NET 读取 ZIP，没有执行 Python。

### 已修复并通过回归

- **基准面高亮和弹窗**：用独立 `pickingPlane` 状态取代 `hint` 文案推断；有实体时也绘制和拾取基准面，选中面有蓝色填充/边框及标签；树和视口上下文工具条恢复，单个基准面显隐、正视、缩放接通。hover 只更新专用通知，避免每次移动重建整棵树。
- **圆角/倒角及其它参数面板**：从原生 feature specs 恢复类型、默认值、引用、多选和字段顺序；真实选边计数、原引用保留、确认时输入不丢失、长表单滚动可达。活动字段接收草图/路径/plane/axis 等参考，按类型过滤，免 Ctrl 连选；仅顶点表单模式优先拾取真实顶点。
- **窗口圆角和边框**：新增 Windows 原生 DWM 适配，恢复窗口圆角偏好、阴影、调整大小、最大化/恢复、DPI 和工作区处理。后续将最小化按钮接入原生 `SC_MINIMIZE`，最大化/还原统一 `SC_MAXIMIZE/SC_RESTORE`；不走 Qt 无边框几何模拟路径，保留最小化前最大化状态。标题拖动直接使用系统移动，样式被重置后重新施加原生标志。Windows 11 回归通过，未更改系统动画设置；Windows 10 圆角仍依赖系统回退。
- **草图模式的参考残留**：修复进入草图时画布 XY/XZ/YZ 悬空标注没有通知 QML 刷新的根因；专用去重 `labelsChanged` 覆盖草图生命周期、相机、显隐及尺寸，不触发整树重建。进入草图关闭旧基准面/特征浮条并清目标，编辑入口清 `pickingPlane`，保护当前草图和视线，独立排除已存编辑 owner 避免旧几何叠画；草图框放真正缩放并保留草稿，进出清理 hover/zoom。左侧参考基准面条目保留。
- **选择、上下文与取消**：视口点击打开工具条、空白关闭，双击基准面进草图/特征进编辑；Esc 关闭上下文、取消测量和框缩放，包括取消后迟到鼠标释放。只选单面/边不会把所属特征整件染蓝，纯选特征仍整体高亮。
- **装配误删与菜单**：零件/运动副互斥；Delete 根据当前类型派发，无目标不操作；普通空白/平面点击清除旧删除目标，Ctrl 空白保留加选目标；`part:n` 工具条路由、改名、打开/返回和重排引用修复，用户文件没有被自动重写。
- **设计检查与规则**：GUI 调用真实 `check_design`，显示实际 counts/issues/red；规则持久化并按文档覆盖用户优先级合并；工艺绑定与树徽标接通。未绑定工艺仍继续几何薄壁检查；材质、有效规则及修订参与过期判定，输入变化会撤销旧标红，排队/执行变化不会被当作有效报告。
- **外观与错误标红**：材质回退、特征颜色和持久化 `feature_opacity` 接到绘制；“跟随材质”不再被默认蓝灰色覆盖。原生显示边表加入所属特征和 origin，边拾取/隐藏/线框错误标红读取同一归属，接触不同特征的边采用相邻面的较晚特征归属。
- **工程图兼容**：读取并无损保留旧 linear(h/v/a)、round(Ø/R) 尺寸及扩展字段；新尺寸保存同视图坐标，跟随移动、比例、纸张、布局和显隐；旧 `_grid` 基位、34 mm 间距、标题区和 offsets 恢复。坏尺寸拒绝替换当前文档，缺失零件仍保留原数据。已有原生 `page_*` 尺寸缺视图归属时保留原位置并提示，避免猜测关联。
- **源码快捷方式**：当前 `launch-from-source.cmd` 增量构建并运行独立 `build/window-native`，支持 `GENFORM_BUILD_DIR`。前轮保留 PID19676；本轮保留用户仍在 `build/ui-fix` 中编辑草图的 PID9916，未停止或覆盖旧实例。

### 实际验收证据

- 完整 MSVC / Qt 6.9.1 / OCCT 本地构建成功；测试未依赖 Python。
- 首轮新增 8 项和既有 16 项全部通过；本轮扩充后在 `build/window-native` 运行完整 **25/25、0 失败、164.00 秒**。选择套件 **49/49** 无 QML 警告，Windows 窗框 **149 项**通过。新增断言包含真 QML 鼠标/键盘、原生几何、图像像素和 HWND 原生命令。
- 通过 `launch-from-source.cmd --gui-smoke-test` 验证桌面同一路径：65 项通过，`qmlWarnings: []`。
- 另开修复版进程读取示例零件，直接观察 Windows 窗口圆角；点击 XY 树行后实际看到树高亮、三维基准面蓝色高亮及四按钮工具条。随后正常关闭此临时只读预览，未操作 PID19676 的未保存模型。
- 本轮另开 PID9828，点击基准面并按 S，直接截图确认草图画布没有 XY/XZ/YZ 残留标签且旧浮条关闭，左侧参考列表保留；临时窗口随后正常关闭，PID9916 保持运行。真实窗口按钮测试确认原生命令及最终状态，系统 `SPI_GETANIMATION` 与 client-area 动画均开启、DWM 合成开启。尝试连续画面录制时本机 PowerShell 脚本策略拒绝执行，未绕过或更改策略，因此不把命令测试冒充逐帧视觉动画证明。

### 仍未补齐，不能宣称迁移等价

1. 实体特征的实时 ghost 预览、拉伸拖拽箭头仍缺；当前面板明确提示确认后由内核重建。
2. 剖切 offset/flip、透视、卡通，以及 HLR/HLV、更多场景和参考分类显隐未完整迁移；对应未实现操作仍显式报告不支持。
3. 右键八方向手势轮及自定义设置没有完整执行链。
4. 设计树文件夹、吸收草图层级与折叠展开未恢复；特征上下文细分操作、任意曲面正视仍不齐全。
5. 工程图仍是网格边线投影，未恢复精确 BRep HLR；新建圆尺寸/圆心捕捉、部分取消操作仍待补。工程图 Undo/Redo 旧版同样禁用，应视为新能力而非既有迁移回归。
6. 部分装配高级工具（如螺纹对齐）、装配独立 tints/alpha 与其它复杂选择策略仍需专项迁移和验收。

## 修复前的静态发现（历史记录）

日期：2026-11-02。范围：归档 `migration/python-original-2026-11-02.zip` 中旧 controller/actions/settings/view 与当前 C++/QML 契约。

## 结论与验证边界

- 本轮仅新增此报告；未改代码、未解压/执行旧 Python、未安装依赖、未启动 GUI、未执行测试。以下是**静态确认的错误链与待运行验收步骤**，不是声称已经交互复现。
- 旧文件通过 .NET ZipArchive/StreamReader 直接读取。当前源码有其他代理并行改动（`feature_forms.cpp` 已出现），故优先按**路径 + 函数**定位；行号是审计时的锚点，可能继续变化。
- 父代理负责 planes/contexts；forms/leftpanel 交给对应代理。本报告不修改他们的文件，也不把正在替换的旧表单实现当作最终缺陷重复上报。
- 扫描 `qml/*.qml` 的 `app.<name>` 引用，未发现单纯漏声明的名称；大量名称通过 `GENFORM_UNSUPPORTED` 存在，**名称能绑定不等于功能已接通**。`appearanceColors` 的字符串列表与 QML `required property string modelData` 类型一致；`sim.assembly` 实际返回零件列表，因此 `returnAssembly` 的 `.toList()` 不是 map/list 错配。

## 优先修复的 10 项

### 1. P1：选中运动副后 Delete 会删除先前选中的零件

- **路径/函数**：`qml/AssemblyTree.qml:232` 的运动副 TapHandler；`genform/controller/simulation_bridge.cpp:364` `SimulationBridge::selectJoint()`；`genform/controller/controller.cpp:311` `AppController::runAction("edit.delete")`；`simulation_bridge.cpp:341` `removePart()`。
- **错误链**：先 `selectPart(n)` 保留 `picked_=n` → 点击运动副只赋 `joint_=index`，不清 `picked_`/零件 selection → Delete 在 assembly 分支无条件 `removePart(value("picked").toInt())` → 删除与当前运动副 UI 无关的旧零件，并连带清理它的 mates/joint 引用。
- **旧版对照**：zip `genform/sim/motion.py:311` `selectJoint()` 在选择运动副时明确 `self._picked = -1`；旧 shortcut 也没有当前新增的无条件装配零件删除分支。
- **用户后果/验收**：打开含至少两零件及运动副的装配体，先点零件再点运动副再按 Delete；预期不能误删零件。该序列是源码推导的待运行用例。
- **建议**：建立互斥的 selection kind；选 joint 时清 part selection；Delete 按 joint/part/草图类型派发，未选中则不操作；补 `selectPart → selectJoint → Delete` 回归。

### 2. P1：“设计检查”绕过已经实现的原生检查，零报错不代表检查通过

- **路径/函数**：`genform/controller/controller.cpp` `AppController::runCheck()`（审计末次约 `646`）、`value("checkCounts"/"checkCompleted"/"checkStale")`（`220–226`）、`toggleCheckHighlight()`；后端 `genform/session.cpp:482` 的 `check_design` 分支。
- **错误链**：可见“设计检查”按钮 → `runCheck()` 只扫 `model.status` 的 `error:`（特征重建错误），**不调用** `execute("check_design")` → 所有非重建类制造/几何问题从日志消失。`checkCounts` 固定 warning/info=0；`checkStale` 固定 false；`checkCompleted` 错用 `checkOpen_`，开关日志即开关“完成”状态；日志“标红”按钮只报 unsupported。
- **不是内核缺失**：`session.cpp:488–490` 已调用 `domain::design_checks()` 并返回 `counts/issues/red`。zip `genform/controller/manufacture.py:90` `runCheck()` 真实执行 `check_design`，并跟踪 revision；`:201` 在模型改变后置 stale、撤旧红色。
- **用户后果/验收**：用已有检查测试中的违规件执行 GUI 检查，与 Session 的 `check_design` 返回对照；再修改模型/关闭日志，检查完成状态和过期提示应独立于 open 状态。当前 6 秒通知承认仅查重建，但常驻日志仍叫“设计检查”，容易误读。
- **建议**：GUI 消费现有 `counts/issues/red`；单独保存 completed、revision、stale；装配检查明确范围；标红必须有实际渲染入口，不能仅留可点击空按钮。

### 3. P1：设计规则为空且“绑定工艺”永远可点但不执行，尽管后端已具备

- **路径/函数**：`qml/SettingsDialog.qml:398–443`；`qml/Main.qml:177`；`genform/controller/controller.cpp:225–226`；`genform/controller/controller.hpp` 的 `GENFORM_UNSUPPORTED(bindProcesses/setRule/resetRules)`；`controller.cpp` `treeRows()`。
- **错误链**：`designRules` 硬编码空列表 → 设置页没有规则输入行；reset/set 均是 unsupported → `binding` 永远 false → “绑定工艺”始终 enabled，但 `bindProcesses()` 仅 toast。树行 `process/processColor/processWhy` 一律空，也不读取后端 feature.process，故即使 API 绑定成功，树仍没有工艺徽标。
- **后端/旧版对照**：`genform/session.cpp:423–431` 已有 get/set_design_rules（user scope 明确需 GUI 设置）；`:482–503` 有 bind_processes 且写回 document。zip `controller/manufacture.py:36/54` 实际绑定；`:211–233` 生成规则表、清洗/持久化设置。
- **用户后果/验收**：设置→设计规则为空；评估→绑定工艺只出现“尚未迁移”；用 Session 绑定后树依旧无 process 信息。
- **建议**：用现有 `rule_table/effective_rules` 形成行模型，区分文档/用户 scope；接通 bind_processes 与忙态；`treeRows()` 从 feature.process 映射徽标及解释。不要为了显示可用而把 scope=user 错传到明确拒绝它的 Session 分支。

### 4. P1：外观只读整件 color，忽略材质色、特征色与透明度

- **路径/函数**：`genform/controller/controller.cpp:86` `refresh()`、`setMaterial()`/`setAppearance()`（约 `601–604`）；`genform/view/viewport.cpp:249–278` `paint()`；`genform/domain/properties.cpp:123` `material_color()`；`genform/session.cpp:441–458`。
- **错误链**：刷新只把 document.props.color 传给单一 `bodyColor_`，color 空则强制 `#91abc6` → “跟随材质”也返回同一默认蓝灰，完全不调用已有 `material_color()` → 每个三角面只按 `bodyColor_` 着色；`feature_colors/feature_opacity` 不被视图消费，alpha 仅在草图模式统一设 95。
- **旧版对照**：zip `controller/viewbar.py:23–37` `_body_color()` 有材质回退，`_push_appearance()` 逐特征传颜色、透明度和检查覆盖色。现 Session 已保存 feature_colors/feature_opacity，`genform/assembly/geometry.cpp:135–165` 还生成材质/特征 tints、alpha；不能把文档数据仍存在等同于 GUI 已显示。
- **用户后果/验收**：给零件选“黄铜”、清除单独 color，再打开含不同特征颜色/透明度的旧文件；材质、玻璃、橡胶等视觉区分丢失。整件 palette 字符串类型本身正确，问题在控制器→渲染数据流。
- **建议**：统一 appearance resolver（整件覆盖→材质→默认），按 feature/origin 应用颜色与 opacity，并验证重开/撤销/清覆盖后的外观；装配显示模型同样应携带并消费颜色，不能从当前零件的 props 给整装配上同一色。

### 5. P2：Esc 只清 selection，没有取消测量、框选放大或工程图标注

- **路径/函数**：`qml/Main.qml:29`；`genform/controller/controller.cpp:340` `escape()`、`toggleMeasure()`、`viewAction("zoom_box")`；`genform/view/viewport.cpp:178/435–439`；`genform/view/sheet.cpp:256–272` `useTool()`/`mousePress()`。
- **错误链**：固定 Esc 调 `escape()` → 无 drawing 分支、不关 measuring_、不清 zoomArmed_ → 清零件选择/关闭 sim 后返回。框选放大只在真正拖完框时复位；工程图的 dimensionStarted_ 继续保留首点；测量 panel 也仍处于测量模式。
- **旧版对照**：zip `controller/documents.py:251–275` 按顺序 `drawing.cancel()`、`viewport.cancel_zoom()`、停止测量，然后才退出其他模式。
- **用户后果/验收**：①点局部放大→Esc→拖框仍被放大；②开测量→Esc→继续点面仍参与测量；③工程图尺寸点首点→Esc→下一点可能接上旧首点，而非取消。
- **建议**：恢复按当前交互模式逐层取消的顺序；为 zoom 提供明确 cancel，drawing 可复用 `useTool("select")` 清 dimensionStarted_，measure 则关模式并发正确通知；不要仅清 selection 假装完成取消。

### 6. P2：手势轮三段全部占位，设置显示空轮盘，右拖没有执行路径

- **路径/函数**：`genform/controller/controller.cpp:223–225`；`controller.hpp` `GENFORM_UNSUPPORTED(setGesture/resetGestures)`；`genform/view/viewport.hpp:39–40`；`qml/Main.qml:335–340`；`qml/SettingsDialog.qml:255–289/376`。
- **错误链**：`gestureWheels` 返回 model/sketch 两个空列表，`gestures` 空列表 → 设置无 8 格可选；`gestureActive()` 永远 false / index=-1 → 主轮盘永不出现；Viewport 没有 gestureTriggered 信号/右拖选择执行状态机 → 即便填 rows 也不会运行。
- **旧版对照**：zip `controller/shortcuts.py:124–139` 从两套 8 格设置建模、更新并持久化；`controller/controller.py:99` 连接 `viewport.gestureTriggered → runGesture`。
- **用户后果/验收**：设置→鼠标笔势只有空圆盘；视图按右键拖任意方向不出命令。需同时验两套 wheel，不能只补一个列表。
- **建议**：恢复 action id 八槽契约及设置读写，再连接 press/move/release 识别和 action 派发；未完成前不应给出“右键一划执行”的可用说明。

### 7. P2：装配体 ContextBar 的“重命名”到达错误处理分支，只有右键菜单能改名

- **路径/函数**：`genform/controller/simulation_bridge.cpp:325–331` `partMenu()`/`partContext()`/`partAction()`；`qml/AssemblyTree.qml:43–53/103–132`；`qml/ContextBar.qml:15–25`；`controller.cpp` `applyContext()` 的 part: 分流（由父代理正在修复）。
- **错误链**：partContext 直接复用含 `rename` 的 partMenu → 左键选零件出现 ContextBar → 点 rename 走 contextAction/partAction → `partAction()` 无 rename 分支/无 renameRequested 信号，仅 unsupported。真正打开重命名输入框的是 `AssemblyTree.qml` **右键** MenuList.onPicked 专有逻辑，ContextBar 不经过它。场景右键 `Main.qml:374` 对 part: 直接调用 partAction，也没截 rename。
- **旧版对照**：zip `genform/sim/assembly.py:395` 的 partMenu 与 partContext 是不同契约；旧版的 context 工具条不会简单借用需要 QML 专有弹窗处理的菜单列表。
- **用户后果/验收**：对同一零件，树右键→重命名可弹框；树左键工具条或视图右键→重命名无输入框。这是可见菜单项的路由差异，不是“Popup 全没迁移”。
- **建议**：把 rename 请求提升成统一 signal（index/name/anchor），由窗口层承接；或让各 ContextBar 正确拦截到同一个 rename popup。仅新增 part: 分流不能修复 partAction 本身缺失的 rename 处理。**请父代理 contexts 一并接收。**

### 8. P2：hover 发通用 changed，整棵树每次鼠标移动重新生成且绕过滚动保存

- **路径/函数**：`genform/controller/controller.hpp:15/131` `GENFORM_PROPERTY(tree)`；`controller.cpp:82` hoverChanged lambda、`treeRows()`、`selected()`；`qml/DesignTree.qml:23–43`；`genform/view/viewport.cpp:464–473`；`qml/StatusBar.qml:15`。
- **错误链**：Viewport 每次 hoverMove 发 hoverChanged → lambda 不判文本变化，并同时 emit changed → tree 的 NOTIFY 也是 changed，getter 每次新建 QVariantList → ListView 重新绑定；这条路径没有 `treeAboutToChange`，而 QML 的 keptY 依赖该信号。selected() 的 changed 同样绕过它。`refresh()` 虽会发 aboutToChange，但不能覆盖所有通知路径。
- **额外状态错误**：C++ 未覆盖 hoverLeaveEvent，也不清 hover_；StatusBar 始终优先显示非空 hoverText，因此移出视图后仍可能压住真实 selectionText；正文只显示原始 feature id，旧版 `_describe(hit)` 的几何描述也被省略。
- **旧版对照**：zip `controller/selection.py:170` 只发 hoverTextChanged；`controller/state.py:32–45` 缓存树、仅 rows 真变时先 aboutToChange 再 treeChanged；`view/viewer/mouse.py:329/378–392` 比较 hit 并在离开时清 hover。
- **用户后果/验收**：长历史树滚到中部，在模型上移动鼠标/选中项；检查 tree model reset、滚动跳动、popup 锚点抖动与状态栏遗留。是否发生每帧重建及耗时需实际 Qt 运行测量，不能把静态高频通知直接写成已测性能结果。
- **建议**：tree 单独 NOTIFY treeChanged，缓存/比较行数据，变更前保存滚动；hover 专用 notify 且值不变不发；补 leave 清理和几何描述。与父代理 tree/context 修复协调，不要只补某一个 emit。

### 9. P2：剖切、透视、卡通 UI 完整存在，但方法主动丢弃参数

- **路径/函数**：`qml/ViewBar.qml:48–111/167–171`；`genform/controller/controller.cpp` `toggleViewSetting()`/`setSection()`（审计末次约 `599–600`）；`runAction("view.section"/"view.perspective")`；`genform/view/viewport.cpp:62–64`。
- **错误链**：剖切 plane/offset/flip、透视/卡通按钮以及快捷键全可用 → setSection 的 plane/offset 直接 Q_UNUSED，toggleViewSetting 一律 unsupported → 初始 view_.section/perspective/cartoon 永远不变；投影函数始终线性正交，亦没有渲染端剖切数据入口。
- **旧版对照**：zip `controller/viewbar.py:39` `_apply_view()` 组装 section；`:127–137` 真实更新开关、plane、offset 并应用视图。
- **用户后果/验收**：有实体时点剖切 plane、改 offset/flip、开透视或卡通，图形及 active 状态都不改变；不能用“popup 能打开”作为迁移完成验收。
- **建议**：先使 view state 与渲染功能成对实现、补取消/切文档复位；若暂不实现，至少明确禁用对应可见控件而非保留假可操作按钮。

### 10. P2：圆角仅画了边线，旧版 Win32 原生窗体能力没有等价入口

- **路径/函数**：`qml/Main.qml:21/626–633`；`genform/controller/controller.cpp:72` `attach()`、`toggleMaximize()`；`genform/bootstrap.cpp:71–79`。
- **错误链**：窗口仍是 FramelessWindowHint；QML 只在全窗上画 radius=8 的透明 Rectangle 边线，不能裁掉 window 的实际方角。C++ attach() 只装普通 QObject eventFilter（处理 Close），没有 DWM corner preference / native frame bridge；toggleMaximize 用 Qt visibility==Maximized，而 QML 自己已经把 FullScreen 也当作 maximized。
- **旧版对照**：zip `controller/controller.py:86–91` attach_window 调 `enable_native_frame`、`round_corners`；`genform/win32_frame.py:77–117` 恢复 WS_THICKFRAME 等、WM_NCCALCSIZE/DWM 属性；`:120–131` native_max_toggle 用 IsZoomed 兼容无边框被 Qt 报为 FullScreen 的情况。
- **用户后果/验收**：Windows 11 窗口实际裁剪/阴影/最大化动画/贴边行为丢失；特定全屏工作区状态下最大化按钮可能不能还原。视觉及系统行为须在 Windows GUI 实机验收；静态全仓未找到等价 DwmSetWindowAttribute/NativeEventFilter 实现。
- **建议**：将 Win32 行为封成平台窗体适配器并接入 attach，区分系统圆角和 QML 描边；最大化/还原统一判断 Max/FullScreen 或原生 IsZoomed，验证多屏/DPI/任务栏场景。**父代理已知圆角项，供实现根因定位。**

## 已查、另行归属及避免误报

### 保存与未存提醒

- 当前 `AppController::confirmDiscard()`（`controller.cpp:229–238`）已经真实检查 part/assembly/drawing dirty，Close 安装了 eventFilter；new/open/showStart 都经过它。**不能报告“未存提醒完全没有”。**
- 当前对话框仅 Discard/Cancel，没有 Save 选项；若产品要求“保存/不保存/取消”，需要显式增加异步保存后续动作，而不是直接继续 Close。旧归档本轮未找到同等三按钮实现，因此这应标为交互增强，不冒充已证实的迁移回归。
- `showStart()` 也弹“放弃修改”，但只设 start_=true，并未清文档/dirty；旧版 `documents.py:46–49` 仅盖上开始页。此处文案/行为不一致，优先于增加又一套冗余提醒。

### forms / leftpanel（交表单代理，未改文件）

- 并行代理已经抽出 `genform/controller/feature_forms.cpp`；本轮**不把早先的 makeForm 通用 JSON 表单和 previewNote“暂无预览”行号当作当前稳定结论**，请该代理结合 zip `controller/formpick.py`、`preview.py:98` `_run_preview()` 对照完成。
- 稳定的外围证据：`genform/view/viewport.hpp:34` `labels()` 仍直接 `return {}`；`qml/ViewLabels.qml` 依赖 labels 显示 plane/尺寸/关系，且 `selectSketchRelation` 仍是 GENFORM_UNSUPPORTED。补 form 本身不会自动恢复这些 overlay/点选关系契约。注意这不等同于断言草图编辑器完全不绘制尺寸：其自绘通道与 QML labels 是两回事。
- FormPanel 的 `focusField` 早期是 unsupported，但已被并行代理替换，故从本轮主缺陷列表撤下，避免报告已经修掉的旧快照。

### planes / contexts（交父代理，未改文件）

- `contextRequested(x,y)` 名字及 double 参数与 QML `onContextRequested(x,y)` 匹配；审计时 C++ 只有 Esc 发 `(-1,-1)` 关闭信号，正常 selected() 未发打开信号。`sceneContext` 又只用 featureContext，无 plane/face 语义，scene bar“缺失”是**缺正向 emit 与菜单构建**，不是 QML handler 拼写错。
- `featureMenu()` 简单等于 featureContext；treeMenu material/origin 也落入 featureContext(空 id) 而为空。重命名等更多菜单被短列表省掉；请沿现有 rowMenu/ContextBar 生命周期修复，不要把 popup 放进会重建的行 delegate。
- 第 7、8 项特别需与父代理分工同步。`layoutSketches` 硬编码空列表属于装配布局草图，父代理应决定是否同批接入，不能仅改列表掩盖底层编辑/持久化。

### 另一处明确可见空按钮：对齐螺纹

- `controller.hpp:87` `GENFORM_UNSUPPORTED(alignThreads)` 对应 `Main.qml:222`、`AssemblyProps.qml:416`、`SimPanel.qml:280` 三个可见按钮；`SimulationBridge::runFasteners()`（`simulation_bridge.cpp:397`）虽把真实检查结果放进 result_，alignThreads 却不消费 fix。
- zip `genform/sim/assembly.py:696` 读取 fasteners.fix 并更新目标 `.gform` 特征相位。此修复会写零件文件，需核验源路径/修改目标、保存/重建/失败回滚后再接入；本轮只记录，不执行或代写。可由第三代理与第 1/7 项一起负责装配交互。

## 建议交接顺序与验收

1. 第三代理先修第 1 项删除目标隔离；再接第 2/3 项现成后端，而非重新实现检查算法。
2. 父代理 contexts/planes 修复时合并第 7/8 项契约和 popup 路由；圆角按第 10 项平台入口处理。
3. 表单代理处理 preview/form picking/labels 时与第 5 项取消链协同，避免 Esc 又落回全局清选择。
4. 外观与第 9 项渲染状态可独立修复；新增“同文件 GUI 与 API 检查/外观结果一致”的验收。
5. 已阅读 `genform/controller/gui_smoke.cpp`，其现有程序化场景不等于上述真实 popup/hover/Win32 交互验证；本轮没有运行它，也不声称现测试通过。修复后应补针对具体序列的测试，再跑已有 GUI smoke，最后检查 qmlWarnings 及原生窗体实际表现。

## 独立复核：剩余可见交互（2026-11-02）

本节是后续源码快照的增量结论，前文行号/占位项可能已被并行代理替换，不能把前文 10 项原样当成当前缺陷。已确认 `feature_forms.cpp`、manufacture/simulation 接线及新增 viewport 外观接口存在；不重复审计父代理的选择高亮、plane popup、context 或 native corners。只通过 .NET ZipArchive/StreamReader 阅读归档；本轮只修改本 Markdown，未执行 Python、编译、测试、GUI 或桌面操作，未接触 PID 19676 及其未保存文档。下述“结果”均为静态调用链推导，不是实机复现。

### P1：工程图标注兼容与关联性

1. **旧版带尺寸 `.gdrw` 明确被拒绝打开。** `genform/view/sheet.cpp:291–301` 的 `DrawingBridge::open()` 对任意不含 `page_a` 的尺寸直接抛出“旧版尺寸关系尚未支持”。归档 `genform/drawings/files.py:37–39/63` 保存的是 `dimensions=_dims`；`drawings/mouse.py:83–105` 创建的是 `{view,a,b,kind,mode,at}` 或 `{view,kind:'round',c,r,...}`，都没有 `page_a`。因此这不是仅缺画法，而是旧工程图工作流被阻断；当前拒绝覆盖是保护措施，不应移除保护而静默丢弃尺寸。建议先提供只读兼容/显式转换，再允许另存。
2. **新标注与视图脱钩，移动/缩放/隐藏视图后尺寸会留在原纸面位置。** `sheet.cpp:263–272` 将点击的纸面坐标存为 `page_a/page_b/page_at`，一次计算并固定 `value`，没有 `view`；`refresh():215–226` 无条件画这些原坐标，而视图单独在 `196–205` 应用 offsets/scale。`toggleView():250–254` 也不处理尺寸。旧版 `drawings/layout.py:76/87–102/188–190` 每次依视图 placement 转换模型坐标，并只画仍可见视图的尺寸。另有同一交互缺口：当前只接受任意三次点击、没有端点/圆心捕捉、直径/半径、斜向真长度及标注 hover 预览（`sheet.cpp:261–290`）；旧版 `drawings/mouse.py:63–105` 均有对应分支。建议先恢复模型坐标 + 视图归属，再补捕捉/圆与斜向尺寸，避免把不精确纸面尺寸当成工程尺寸。

### P1/P2：表单已新增，但拾取与预览外围未闭环

3. **P1：拉伸“成形到顶点”存在表单但没有顶点输入路径；P2：active 字段及免 Ctrl 连选未落地。** `feature_forms.cpp:111–114/65–78/295–305` 明确要求 `selection.vertices`；但 `Viewport::pick()`（`viewport.cpp:376–409`）只返回 edges/faces/feature/plane，从不产生 vertices；`AppController::selected():393–400` 加选也只合并 faces/edges。`focusField():252–254` 只存 `form_["active"]`，当前 C++ 没有读取它并按字段接收 sketch/path/axis/plane 的消费者；`selected():403–407` 仅对边做固定 key 的转写。普通点选仍按 Ctrl 决定 additive（`viewport.cpp:489–491`），与表单说明“再点一次取消”和旧版免 Ctrl 多选不符。旧版 `controller/selection.py:37–75` 有顶点专门模式、按 pick.kind/count 接收与自动连选，`formpick.py:103–136/192–217` 按 active 字段接收参考几何/草图/轴。**不是重新报“没有 feature forms”**；下拉和确认已存在，缺的是视图到字段的状态链。
4. **P2：动态实体预览与拉伸拖拽箭头仍明确缺失。** `feature_forms.cpp:213` 直接显示“暂不提供动态实体预览”；`setFormFields():257–264` 只更新字段及通知，viewport 的 preview 目前只有草图 `editor_->preview()`（`viewport.cpp:364`），不能当成实体特征预览。归档 `controller/preview.py:50–77` 有拉伸距离/反向拖拽手柄，`:98–138` 有带 ticket 防迟到覆盖的异步实体 ghost 预览。建议接入非提交预览与取消/切文档清理，再补手柄；确认按钮会重建实体不等于实时预览已迁移。

### P2：视图、手势、树与外观

5. **剖切/透视/卡通仍是可点占位，另有整组选项被缩水。** `controller.cpp:607–608` 的 `toggleViewSetting()`、`setSection()` 仍 unsupported；`viewport.cpp:96–98` 只做正交线性投影。对应可见按钮是 `qml/ViewBar.qml:48–111/167–171`。此外 `controller.cpp:200–202/601–604` 只列三种样式、一个 auto 场景、一个 main_planes 显示项；归档 `controller/common.py:55–66` 还提供 hlr/hlv、fade/white/gray/spot 以及 axes/csys/points/origin/curves/sketches 等分类显隐；`viewbar.py:39–48/127–137` 真正把这些状态送入 viewport。建议分清“仍可点但不工作”与“菜单项消失”，逐项恢复或显式禁用，不能只更新按钮 checked 状态。
6. **右键手势轮及自定义没有执行链。** `controller.cpp:232–234` 返回空 model/sketch/gestures，`controller.hpp:280–281` 的 setGesture/resetGestures unsupported，`viewport.hpp:39–40` 永远 false/-1，没有 gestureTriggered 信号。`Main.qml:335–340` 因而不会展示手势轮；`SettingsDialog.qml:255–289` 的两套轮也没有八格内容。归档 `view/viewer/display.py:131–158` 有起动/瞄准/触发阈值与松手触发，`controller/state.py:502–514` 真实 runAction，`shortcuts.py:124–138` 保存/重置配置。建议把识别、八格配置和动作派发作为一条链验收。
7. **新增外观 setter 仍未接通，且 opacity 数据键不匹配。** 当前 `Viewport::setAppearance()`（`viewport.cpp:57`）已存在、paint 已读 `feature_colors`（`:310`），但全体 C++ 调用点检查只有声明/定义，没有 controller 调用；`refresh()`（`controller.cpp:90–91`）仍只 setModel/setColor，整件无颜色时也不调用现有 material_color。即使随后接通，paint 读的是 `feature_transparencies`（`viewport.cpp:314–318`），Session 持久化的是 `feature_opacity`（`session.cpp:447–457`，透明度与不透明度方向也相反）。装配现有 tints/alpha（`assembly/geometry.cpp:140–160`）亦未见 viewport 消费。旧版 `viewbar.py:23–37` 有材质回退、特征颜色与 opacity；故应修“数据流 + 字段语义”，不是再加一份接口。
8. **树的文件夹与被吸收草图层级缺失。** `controller.cpp:104–138` 将所有 feature 固定 depth=1、expandable=false/child=false/folders=0，不读取 feature.folder 或 params.sketch；`controller.hpp:278` toggleExpand 仍 unsupported。QML 的折叠箭头和 folder 行已保留（`DesignTree.qml:194/308–322`），只是模型永远不产生可折叠节点。归档 `controller/state.py:87–94/130–172` 有草图吸收、文件夹层级、折叠与选中自动展开。建议保留原特征次序及 rollback before/after 语义重建树模型；父代理正在修的菜单/popup 路由不等于此层级已恢复，菜单本轮不重复计缺陷。

### 排除误报与待运行验收

- **工程图 Undo/Redo 不是已证实迁移回归。** 当前 `controller.cpp:156–157/334–343` 禁用/unsupported；但归档 `controller/state.py:296–303` 也明确 drawing 时 canUndo/canRedo=false，且 drawings 包没有 history。若要增加工程图历史，应列新功能，不能写成“旧版已有而迁移遗漏”。
- **取消链仍待核实，新增 cancelInteraction 不等于已调用。** 当前 `Viewport::cancelInteraction()` 已存在（`viewport.cpp:59`），全 C++ 没有调用点；`AppController::escape():348–352` 没有 drawing.cancel/停止 measure/取消 zoom；`SheetView::mousePressEvent():87–89` 将右键当平移，未向 DrawingBridge 发送 cancel。旧版 `drawings/mouse.py:117–128`、`view/sheet.py:189–190` 明确取消半成尺寸。建议与父代理模式清理一起修，不在本轮改实现。
- **建议验收顺序（均尚未运行）**：①用旧版有 linear/round 尺寸的 `.gdrw` 只读打开；②新尺寸后移动视图、换比例、隐藏视图；③拉伸到顶点、按 active 字段点选旋转轴、圆角免 Ctrl 连选；④参数拖拽/预览取消；⑤剖切 offset/flip、透视、卡通、右键八方向；⑥材质/feature opacity 重开；⑦含嵌套 folder 与吸收草图的树展开/回退。请另开测试进程或使用隔离测试数据，勿驱动 PID 19676 的未保存程序。
