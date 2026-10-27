// Main.qml - GenForm 主窗口 (无系统边框):
//   标题栏 (文件操作 / 撤销重做 / 窗口按钮) → 工具栏 (建模工具; 编辑草图时换成草图工具)
//   → 左: 基准面 + 特征历史 | 中: 三维视图 | 右: 参数面板 (用到时才出现) → 状态栏
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Window
import GenForm 1.0

ApplicationWindow {
    id: root
    width: 1360
    height: 860
    minimumWidth: 960
    minimumHeight: 600
    visible: true
    title: app.title + " — GenForm"
    color: Theme.cBgWorkspace
    flags: Qt.FramelessWindowHint | Qt.Window

    readonly property bool maximized: visibility === Window.Maximized || visibility === Window.FullScreen
    // 正在输入框里打字: 单字母快捷键、Delete、回车都要让给输入框
    readonly property bool typing: activeFocusItem !== null && activeFocusItem instanceof TextInput


    // ---- 快捷键: 每个功能的键在 "设置" 里改 (app.shortcuts); 只有取消和确认是固定的 ----
    Shortcut { sequence: "Escape"; enabled: !settingsDialog.opened; onActivated: app.escape() }
    Shortcut { sequences: ["Return", "Enter"]; enabled: !root.typing && app.sketchActive && !settingsDialog.opened; onActivated: app.enterKey() }
    Item {
        Repeater {
            model: app.shortcuts
            delegate: Item {
                required property var modelData
                Shortcut {
                    sequence: modelData.key
                    // 正在输入框里打字: 单个字母、Delete 让给输入框; 带 Ctrl 的照常
                    enabled: !settingsDialog.opened && (!root.typing || modelData.key.indexOf("Ctrl+") >= 0)
                             && (!app.startPage || modelData.id === "file.new" || modelData.id === "file.open" || modelData.id === "app.settings")
                    onActivated: app.runAction(modelData.id)
                }
            }
        }
    }
    Connections {
        target: app
        function onDialogRequested(which) {
            if (which === "new") newDialog.open()
            else if (which === "open") openDialog.open()
            else if (which === "save") saveDialog.open()
            else if (which === "export") exportDialog.open()
            else if (which === "settings") settingsDialog.open()
        }
        function onAppearanceRequested() { viewBar.openAppearance() }
        function onContextRequested(x, y) {
            const items = x < 0 ? [] : app.sceneContext
            if (items.length === 0) { sceneBar.close(); return }
            sceneBar.target = app.sceneTarget
            sceneBar.items = items
            // 摆在点的位置的右上方 (不压住刚点的地方); 靠边时往里收
            const wide = Math.min(items.length, 8) * 36 + 10, tall = Math.ceil(items.length / 8) * 32 + 10
            sceneBar.x = Math.max(8, Math.min(viewArea.width - wide - 8, x + 16))
            sceneBar.y = y - tall - 16 < 56 ? y + 22 : y - tall - 16
            sceneBar.open()
        }
    }
    SettingsDialog { id: settingsDialog }
    NewDialog { id: newDialog }

    // 文件拖进窗口: 打开装配体 / 工程图 / 零件, 装配体里拖零件 = 插入零部件 (app.dropFiles 按扩展名分)
    DropArea {
        id: fileDrop
        anchors.fill: parent
        z: 1000
        onEntered: (drag) => drag.accepted = drag.hasUrls
        onDropped: (drop) => { if (drop.hasUrls) { app.dropFiles(drop.urls); drop.accept(Qt.CopyAction) } }
        Rectangle {
            anchors.fill: parent; anchors.margins: 8
            visible: fileDrop.containsDrag
            radius: 10
            color: Qt.rgba(0.16, 0.42, 0.85, 0.12)
            border.width: 2; border.color: Theme.cAccent
            Rectangle {
                anchors.centerIn: parent
                width: dropHint.implicitWidth + 40; height: dropHint.implicitHeight + 24; radius: 8
                color: Theme.cAccentStrong
                Text {
                    id: dropHint
                    anchors.centerIn: parent
                    horizontalAlignment: Text.AlignHCenter
                    text: root.kind === "assembly" ? qsTr("松开：批量插入 STEP / STL / 零件，保留原始坐标")
                                                   : qsTr("松开：打开文件；多个 STEP / STL / 零件自动组成装配体")
                    color: "#FFFFFF"; font.family: Theme.font; font.pixelSize: Theme.textSize + 1
                }
            }
        }
    }

    // 文件对话框跟着开着的文档走: 零件 .gform / 装配体 .gasm / 工程图 .gdrw
    readonly property string kind: app.docKind
    FileDialog {
        id: openDialog
        title: qsTr("打开文件（可多选，多个零件组成装配体）")
        fileMode: FileDialog.OpenFiles
        nameFilters: [qsTr("GenForm / STEP / STL (*.gform *.gasm *.gdrw *.step *.stp *.stl)"), qsTr("零件 / STEP / STL (*.gform *.step *.stp *.stl)"), qsTr("GenForm 装配体 (*.gasm)"), qsTr("GenForm 工程图 (*.gdrw)"), qsTr("STEP 文件 (*.step *.stp)"), qsTr("STL 网格 (*.stl)")]
        onAccepted: app.openFiles(selectedFiles)
    }
    FileDialog {
        id: saveDialog
        title: qsTr("保存")
        fileMode: FileDialog.SaveFile
        defaultSuffix: root.kind === "assembly" ? "gasm" : (root.kind === "drawing" ? "gdrw" : "gform")
        nameFilters: root.kind === "assembly" ? [qsTr("GenForm 装配体 (*.gasm)")]
                   : (root.kind === "drawing" ? [qsTr("GenForm 工程图 (*.gdrw)")] : [qsTr("GenForm 零件 (*.gform)")])
        onAccepted: app.saveDocument(selectedFile)
    }
    FileDialog {
        id: exportDialog
        title: qsTr("导出")
        fileMode: FileDialog.SaveFile
        defaultSuffix: root.kind === "drawing" ? "pdf" : "step"
        nameFilters: root.kind === "drawing" ? [qsTr("PDF 文档 (*.pdf)"), qsTr("DXF 图形，给别的 CAD 用 (*.dxf)"), qsTr("SVG 矢量图 (*.svg)"), qsTr("PNG 图片 (*.png)")]
                   : (root.kind === "assembly" ? [qsTr("STEP 精确几何 (*.step *.stp)")]
                                               : [qsTr("STEP 精确几何 (*.step *.stp)"), qsTr("STL 三角网格 (*.stl)")])
        onAccepted: app.exportModel(selectedFile)
    }
    FileDialog {                            // 装配体的物料清单
        id: bomDialog
        title: qsTr("保存物料清单")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "csv"
        nameFilters: [qsTr("CSV 表格 (*.csv)")]
        onAccepted: sim.exportBill(selectedFile)
    }
    FileDialog {                            // 装配体里插入零件 / 工程图选要画的零件
        id: partDialog
        title: root.kind === "drawing" ? qsTr("选择零件") : qsTr("插入零件")
        fileMode: root.kind === "drawing" ? FileDialog.OpenFile : FileDialog.OpenFiles
        nameFilters: root.kind === "drawing" ? [qsTr("零件 (*.gform *.step *.stp)")] : [qsTr("零件 / STEP / STL (*.gform *.step *.stp *.stl)")]
        onAccepted: root.kind === "drawing" ? drawing.setPart(selectedFile) : sim.addParts(selectedFiles)
    }

    component SectionTitle: Text {
        color: Theme.cTextMuted
        font.family: Theme.font; font.pixelSize: 11; font.bold: true
        Layout.leftMargin: 4
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ================= 标题栏 =================
        TitleBar { onOpenSettings: settingsDialog.open() }

        // ================= 工具栏: 特征 / 草图 两页 (和 SOLIDWORKS 的命令管理器一样, 只是翻页, 不换界面) =================
        Rectangle {
            Layout.fillWidth: true
            height: 96
            color: Theme.cBg
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cDivider }

            // ---- 特征页 (和 SOLIDWORKS 的特征页一个顺序: 凸台 | 切除和孔 | 修改 | 阵列、参考几何体、曲线) ----
            FeatureRibbon {}

            // ---- 草图页 (工具多, 窗口窄时可以左右滚) ----
            SketchRibbon {}

            // ---- 评估页: 量和查 ----
            RowLayout {
                x: 12; y: 6; height: 54
                visible: app.tab === "evaluate" && root.kind === "part"
                spacing: 1
                RibbonBtn { icon: "measure"; text: qsTr("测量"); tip: qsTr("测量：点一个面、边或顶点看它的尺寸；点两个看它们之间的最短距离、夹角、中心距"); action: "eval.measure"; active: app.measuring; onClicked: app.toggleMeasure() }
                RibbonSeparator {}
                RibbonBtn { icon: "process"; text: app.binding ? qsTr("绑定中…") : qsTr("绑定工艺"); tip: qsTr("绑定工艺：按性价比自动给每个特征挑现实里能做的加工工艺（激光切割、折弯、冲压、手工钣金、CNC、车削、铸造、注塑、3D 打印、外购…），按设计规则里的生产数量摊模具费；绑好后设计树的特征名前面显示工艺，悬停看为什么"); action: "eval.process"; enabled: !app.binding; onClicked: app.bindProcesses() }
                RibbonBtn { icon: "drc"; text: app.checkBusy ? qsTr("检查中…") : qsTr("设计检查"); tip: qsTr("设计检查：像 PCB 的 DRC，全部查一遍——特征出错、悬空的零件、件与件间隙太小或只贴着、工艺做不了、壁太薄、孔、尖内角、字太小、成本汇总；有问题的件标红，结果在底部的日志窗口"); action: "eval.check"; active: app.checkOpen; enabled: !app.checkBusy; onClicked: app.runCheck() }
                RibbonBtn { icon: "rules"; text: qsTr("设计规则"); tip: qsTr("设计规则：公差、件与件最小间隙、连接最小压入量、最小壁厚、孔、内角圆角、字高、生产数量（在设置里）"); onClicked: settingsDialog.openPage("rules") }
            }

            // ---- 仿真页: 受力、风阻、装配 ----
            RowLayout {
                x: 12; y: 6; height: 54
                visible: app.tab === "simulate"
                spacing: 1
                RibbonBtn { icon: "stress"; text: qsTr("静力分析"); tip: qsTr("静力分析：选固定面和受力面、填力的大小，估算应力、变形和安全系数"); action: "sim.static"; active: sim.mode === "static"; onClicked: sim.open("static") }
                RibbonBtn { icon: "wind"; text: qsTr("风阻估算"); tip: qsTr("风阻估算：按迎风面积和阻力系数估算空气阻力（不是流场计算）"); action: "sim.drag"; active: sim.mode === "drag"; onClicked: sim.open("drag") }
                RibbonSeparator {}
                RibbonBtn { icon: "assembly"; text: qsTr("装配检查"); tip: qsTr("装配检查：把几个零件摆到一起，查有没有干涉，查按顺序能不能一个个装进去"); action: "sim.assembly"; active: sim.mode === "assembly"; onClicked: sim.open("assembly") }
            }

            // ---- 装配体页: 零部件 (装配体文档有 装配体 / 草图 / 评估 三页, 和 SOLIDWORKS 的装配体一样) ----
            RowLayout {
                x: 12; y: 6; height: 54
                visible: app.tab === "assembly"
                spacing: 1
                RibbonBtn { icon: "plus"; text: qsTr("插入零件"); tip: qsTr("多选 .gform / STEP / STL 文件，批量添加到装配体，也可直接拖入窗口"); onClicked: partDialog.open() }
                RibbonBtn {
                    icon: "screw"; text: qsTr("标准件")
                    tip: qsTr("插入标准件：深沟球轴承、HK 滚针、圆柱销、内六角螺丝、螺母、垫圈、六角铜柱、挡圈、钢球 — 选规格就按国标尺寸生成零件（绑好“标准件”工艺），文件放在装配体旁边的 standard/ 文件夹")
                    onClicked: ribbonStd.start(Qt.point(0, height + 4))
                    StdPicker { id: ribbonStd }
                }
                RibbonSeparator {}
                RibbonBtn { icon: "motion"; text: sim.motion.playing ? qsTr("暂停动画") : qsTr("播放动画"); tip: qsTr("播放动画（运动算例）：所有运动副（车门、车盖…）一起打开、停一下、再关上；视图下面出一条时间轴，可以拖着看。也可以在视图里按住车门直接拖"); active: motionBar.shown; enabled: sim.motion.count > 0; onClicked: { motionBar.shown = true; sim.playMotion() } }
                RibbonSeparator {}
                RibbonBtn { icon: "export"; text: qsTr("导出 STEP"); tip: qsTr("整个装配体导出成一个 STEP 文件：每个零件一个实体，都在摆好的位置上"); onClicked: app.runAction("file.export") }
                RibbonBtn { icon: "cube"; text: qsTr("回到零件"); tip: qsTr("回到零件：离开装配体，继续改现在打开的零件"); onClicked: app.backToPart() }
            }

            // ---- 装配体的评估页: 测量、干涉、装配顺序、设计检查、实时检查、物料清单 ----
            RowLayout {
                x: 12; y: 6; height: 54
                visible: app.tab === "evaluate" && root.kind === "assembly"
                spacing: 1
                RibbonBtn { icon: "measure"; text: qsTr("测量"); tip: qsTr("测量：点一个零部件看它的长宽高、体积、表面积；点两个看它们之间最短的距离和 ΔX ΔY ΔZ（视图里连一条线）"); action: "eval.measure"; active: app.measuring; onClicked: app.toggleMeasure() }
                RibbonSeparator {}
                RibbonBtn { icon: "clash"; text: qsTr("干涉检查"); tip: qsTr("干涉检查：零件两两求重叠，有重叠的标出来"); onClicked: sim.runInterference() }
                RibbonBtn { icon: "order"; text: qsTr("装配顺序"); tip: qsTr("装配顺序检查：自己找一个能装的顺序（按拆卸倒推），装不进去的零件标出挡路的件"); onClicked: sim.runSequence() }
                RibbonBtn { icon: "thread"; text: qsTr("螺纹检查"); tip: qsTr("螺纹检查：螺丝和螺纹孔自动配对，查拧进去够不够长（铝 1.5d、钢 1d）、螺丝尖会不会顶到孔底、两边的螺纹相位对不对得上"); onClicked: sim.runFasteners() }
                RibbonBtn { icon: "check"; text: qsTr("对齐螺纹"); tip: qsTr("对齐螺纹相位：按螺纹检查算出来的相位改螺纹孔特征，螺丝和孔的牙正好咬上（不用手算 360×Δz/螺距）"); onClicked: sim.alignThreads() }
                RibbonBtn { icon: "dimension"; text: qsTr("尺寸链"); tip: qsTr("尺寸链 / 高度分配：沿一根轴把装配体切成一段段，列出每一段多高、里面是哪几个零件 — 看高度都花在哪了"); onClicked: sim.runStack("Z") }
                RibbonSeparator {}
                RibbonBtn { icon: "drc"; text: app.checkBusy ? qsTr("检查中…") : qsTr("设计检查"); tip: qsTr("装配体的设计检查：零件之间有没有压进去（干涉）、间隙是不是太小、有没有悬空没装在任何东西上的零件、零件绑没绑工艺，再按标准件 / 外购件 / 非标件汇总物料清单和成本；有问题的零件标红，结果在底部的日志窗口"); active: app.checkOpen; enabled: !app.checkBusy; onClicked: app.runCheck() }
                RibbonSeparator {}
                RibbonBtn { icon: "props"; text: qsTr("物料清单"); tip: qsTr("物料清单（BOM）：每种零件几件、标准件还是非标件、规格、工艺、材质、估算单价，存成 CSV（Excel 能直接打开）"); onClicked: bomDialog.open() }
                RibbonBtn { icon: "rules"; text: qsTr("设计规则"); tip: qsTr("设计规则：公差、件与件最小间隙…（在设置里）；实时检查和设计检查都按它查"); onClicked: settingsDialog.openPage("rules") }
            }

            // ---- 工程图页 ----
            RowLayout {
                x: 12; y: 6; height: 54
                visible: app.tab === "drawing"
                spacing: 1
                RibbonBtn { icon: "open"; text: qsTr("选择零件"); tip: qsTr("选择零件：这张图纸画哪个零件（.gform 或 .step 文件）"); onClicked: partDialog.open() }
                RibbonSeparator {}
                RibbonBtn { icon: "dimension"; text: qsTr("智能尺寸"); tip: qsTr("智能尺寸：点两个点（线的端点、圆心），再点一下放下——上下拉出去是水平尺寸，左右拉出去是竖直尺寸；点一个圆 = 标直径"); active: drawing.state.tool === "dimension"; onClicked: drawing.useTool("dimension") }
                RibbonBtn { icon: "trash"; text: qsTr("删除尺寸"); tip: qsTr("删除选中的那个尺寸（先点一下它的数字；按 Delete 也行）"); enabled: drawing.state.selected; onClicked: drawing.deleteSelected() }
                RibbonSeparator {}
                RibbonBtn { icon: "fit"; text: qsTr("整张图纸"); tip: qsTr("把整张图纸放满窗口"); onClicked: drawing.fit() }
                RibbonSeparator {}
                RibbonBtn { icon: "export"; text: qsTr("导出"); tip: qsTr("导出：PDF / DXF / SVG / PNG"); onClicked: app.runAction("file.export") }
                RibbonBtn { icon: "cube"; text: qsTr("回到零件"); tip: qsTr("回到零件：离开工程图，继续改现在打开的零件"); onClicked: app.backToPart() }
            }

            // ---- 页签 ----
            Row {
                x: 12
                anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                spacing: 4
                Repeater {
                    model: root.kind === "assembly" ? [{ id: "assembly", text: qsTr("装配体") }, { id: "sketch", text: qsTr("草图") }, { id: "evaluate", text: qsTr("评估") }]
                         : (root.kind === "drawing" ? [{ id: "drawing", text: qsTr("工程图") }]
                         : [{ id: "feature", text: qsTr("特征") }, { id: "sketch", text: qsTr("草图") }, { id: "evaluate", text: qsTr("评估") }, { id: "simulate", text: qsTr("仿真") }])
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: app.tab === modelData.id
                        width: tabText.implicitWidth + 30; height: 24; radius: 12
                        color: on ? Theme.cAccentStrong : (tabArea.containsMouse ? Theme.cBgHover : Theme.cBgWorkspace)
                        Behavior on color { ColorAnimation { duration: 120 } }
                        Text {
                            id: tabText
                            anchors.centerIn: parent
                            text: modelData.text
                            color: parent.on ? "#FFFFFF" : Theme.cTextSec
                            font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: parent.on
                        }
                        MouseArea { id: tabArea; anchors.fill: parent; hoverEnabled: true; onClicked: app.setTab(modelData.id) }
                    }
                }
                // 从装配体打开的零件 (或 "回到零件" 过来的): 改完点它回装配体; 零件改过就先存
                Rectangle {
                    id: backChip
                    visible: app.returnAssembly !== ""
                    readonly property bool unsaved: app.title.endsWith(" *")
                    width: backRow.implicitWidth + 24; height: 24; radius: 12
                    color: backArea.containsMouse ? Theme.cAccentSoft : Theme.cBgWorkspace
                    border.width: 1; border.color: Theme.cAccentLine
                    Row {
                        id: backRow
                        anchors.centerIn: parent; spacing: 5
                        Icon { anchors.verticalCenter: parent.verticalCenter; size: 14; name: "assembly"; color: Theme.cAccent }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: (backChip.unsaved ? qsTr("保存并返回装配体 ") : qsTr("返回装配体 ")) + app.returnAssembly
                            color: Theme.cAccent; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true
                        }
                    }
                    MouseArea { id: backArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: app.backToAssembly() }
                    Tip { shown: backArea.containsMouse; text: app.sketchActive ? qsTr("正在编辑草图：先点“完成草图”或“放弃”，再返回装配体")
                                                                              : qsTr("回到装配体：零件改过会先保存，装配体里它跟着重算") }
                }
            }
        }

        // ================= 主体 =================
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ---- 左: 设计树 / PropertyManager 两页 ----
            LeftPanel { onChoosePart: partDialog.open() }

            // ---- 中: 三维视图 ----
            Item {
                id: viewArea
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                Viewport {
                    id: viewport
                    objectName: "viewport"
                    anchors.fill: parent
                    visible: root.kind !== "drawing"
                    dark: Theme.darkMode
                }

                // 视图里的文字: 基准面的名字、草图的尺寸; 草图里的几何关系小图标 (kind "relation", x / y 是中心;
                // 点它 = 选中这个关系, 属性管理器里能删, 也可以按 Delete)
                ViewLabels { view: viewport }

                // 装配体的动画: 时间轴 (播放 / 暂停 / 拖着看)
                MotionBar {
                    id: motionBar
                    visible: shown && motion.count > 0 && root.kind === "assembly"
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom; anchors.bottomMargin: app.checkOpen ? 320 : 20
                    z: 15
                }

                // 右键拖动出现的手势轮
                GestureWheel {
                    visible: viewport.gestureActive
                    x: viewport.gestureX - width / 2
                    y: viewport.gestureY - height / 2
                    items: app.gestures
                    current: viewport.gestureIndex
                }

                // 现在该干什么 (选基准面、草图工具的用法)
                Rectangle {
                    anchors.top: parent.top; anchors.topMargin: 58
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: app.hint !== ""
                    width: hintText.implicitWidth + 28; height: 30; radius: 15
                    color: Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.90)
                    border.width: 1; border.color: Theme.cAccentLine
                    Text {
                        id: hintText
                        anchors.centerIn: parent
                        text: app.hint
                        color: Theme.cText
                        font.family: Theme.font; font.pixelSize: Theme.smallSize
                    }
                }

                // 视图上方正中的一排小按钮: 取景、剖切、视图定向、显示样式、显示哪些东西、外观、布景
                ViewBar {
                    id: viewBar
                    anchors.top: parent.top; anchors.topMargin: 10
                    anchors.horizontalCenter: parent.horizontalCenter
                    view: viewport
                }

                // 视图里右键单击 (没拖成手势轮): 弹出右键菜单, 和设计树里右键那个特征的一样; 点在空白处是零件的菜单
                MenuList {
                    id: viewMenu
                    property string target: ""
                    itemWidth: 196
                    onPicked: (id) => {
                        if (target.startsWith("part:")) sim.partAction(parseInt(target.slice(5)), id)       // 装配体的零部件
                        else if (target === "") app.treeAction("root", "", id)
                        else if (id === "rename") { viewRename.target = target; viewRename.x = viewMenu.x; viewRename.y = viewMenu.y; viewRename.open() }
                        else if (id === "delete") app.deleteFeature(target)
                        else app.contextAction(target, id)
                    }
                }
                Popup {                     // 右键菜单里点了 "重命名": 光标那里弹一个输入框
                    id: viewRename
                    property string target: ""
                    width: 220; height: 30
                    padding: 0
                    background: Rectangle { color: Theme.cBgInput; radius: 6; border.width: 1; border.color: Theme.cAccent }
                    onOpened: { viewRenameInput.text = app.featureName(target); viewRenameInput.selectAll(); viewRenameInput.forceActiveFocus() }
                    contentItem: TextInput {
                        id: viewRenameInput
                        leftPadding: 8; rightPadding: 8
                        verticalAlignment: TextInput.AlignVCenter
                        color: Theme.cText
                        selectionColor: Theme.cAccentStrong
                        font.family: Theme.font; font.pixelSize: Theme.textSize
                        selectByMouse: true
                        clip: true
                        onAccepted: { app.renameFeature(viewRename.target, text); viewRename.close() }
                        Keys.onEscapePressed: viewRename.close()
                    }
                }
                Connections {
                    target: app
                    function onViewMenuRequested(identifier, x, y) {
                        const items = identifier.startsWith("part:") ? sim.partMenu(parseInt(identifier.slice(5)))
                                    : identifier !== "" ? app.featureMenu(identifier) : app.treeMenu("root", "")
                        if (items.length === 0) return
                        viewMenu.target = identifier
                        viewMenu.items = items
                        viewMenu.x = Math.min(x, viewArea.width - viewMenu.itemWidth - 12)
                        viewMenu.y = Math.min(y, Math.max(0, viewArea.height - 40 - items.length * 32))
                        viewMenu.open()
                    }
                }

                // 设计检查的日志: 从视图底部滑上来 (评估 → 设计检查)
                CheckLog {
                    z: 20
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.leftMargin: 10; anchors.rightMargin: 10
                    allowed: root.kind === "part" || root.kind === "assembly"
                }

                // 孤立中: 工具条下面一条提示, 点 "退出孤立" 回到原来的样子
                Rectangle {
                    objectName: "isolateBar"
                    visible: root.kind === "assembly" ? sim.isolatedName !== "" : app.isolatedName !== ""
                    anchors.top: viewBar.bottom; anchors.topMargin: 8
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: isolateRow.implicitWidth + 20; height: 34
                    radius: 9
                    color: Theme.cBgCard
                    border.width: 1; border.color: Theme.cAccentLine
                    Row {
                        id: isolateRow
                        anchors.centerIn: parent
                        spacing: 10
                        Icon { anchors.verticalCenter: parent.verticalCenter; name: "isolate"; size: 17; color: Theme.cAccent }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: qsTr("孤立：") + (root.kind === "assembly" ? sim.isolatedName : app.isolatedName)
                            color: Theme.cText
                            font.family: Theme.font; font.pixelSize: Theme.smallSize
                        }
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: exitText.implicitWidth + 20; height: 24; radius: 6
                            color: exitArea.containsMouse ? Theme.cAccentStrong : Theme.cAccentSoft
                            Text {
                                id: exitText
                                anchors.centerIn: parent
                                text: qsTr("退出孤立")
                                color: exitArea.containsMouse ? "#FFFFFF" : Theme.cAccent
                                font.family: Theme.font; font.pixelSize: Theme.smallSize
                            }
                            MouseArea {
                                id: exitArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.kind === "assembly" ? sim.exitIsolation() : app.toggleShow("isolate_exit")
                            }
                        }
                    }
                }

                // 局部放大时拖出来的框
                Rectangle {
                    readonly property var box: viewport.zoomRect
                    visible: box.length === 4
                    x: visible ? box[0] : 0; y: visible ? box[1] : 0
                    width: visible ? box[2] : 0; height: visible ? box[3] : 0
                    color: Qt.rgba(Theme.cAccent.r, Theme.cAccent.g, Theme.cAccent.b, 0.12)
                    border.width: 1; border.color: Theme.cAccent
                }

                // 左键拖出来的选择框: 蓝色。从左往右拖 = 整个在框里的才选中 (实线); 从右往左拖 = 碰到框的都选中 (虚线)
                Shape {
                    id: bandShape
                    readonly property var band: viewport.band
                    anchors.fill: parent
                    visible: band.length === 4
                    ShapePath {
                        strokeColor: Theme.cAccent
                        strokeWidth: 1.2
                        strokeStyle: viewport.bandCrossing ? ShapePath.DashLine : ShapePath.SolidLine
                        dashPattern: [5, 3]
                        fillColor: Qt.rgba(Theme.cAccent.r, Theme.cAccent.g, Theme.cAccent.b, 0.14)
                        PathPolyline {
                            path: bandShape.visible ? bandShape.band.concat([bandShape.band[0]]).map((p) => Qt.point(p[0], p[1])) : []
                        }
                    }
                }

                // 在视图里点中面 / 边 / 草图线弹出来的小工具条
                ContextBar { id: sceneBar }

                // 确认角 (草图里才有): ✓ 保存并退出草图, ✕ 放弃这次画的
                Column {
                    anchors.top: parent.top; anchors.topMargin: 14
                    anchors.right: parent.right; anchors.rightMargin: 14
                    spacing: 8
                    visible: app.sketchActive
                    Repeater {
                        model: [{ icon: "finish", tint: Theme.cGood, tip: qsTr("完成草图：保存并退出") },
                                { icon: "cancel", tint: Theme.cBad, tip: qsTr("放弃：不保存这次画的，退出草图") }]
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: 44; height: 44; radius: 22
                            color: cornerArea.containsMouse ? modelData.tint : Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.88)
                            border.width: 1.5; border.color: modelData.tint
                            Icon { anchors.centerIn: parent; size: 24; name: modelData.icon; color: cornerArea.containsMouse ? (index === 1 && Theme.darkMode ? "#000000" : "#FFFFFF") : modelData.tint }
                            MouseArea {
                                id: cornerArea
                                anchors.fill: parent; hoverEnabled: true
                                onClicked: index === 0 ? app.finishSketch() : app.cancelSketch()
                            }
                            Tip { shown: cornerArea.containsMouse; text: modelData.tip }
                        }
                    }
                }
                // 重算的进度条: 视图下方正中
                ProgressCard { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 28 }

                // 草图里选中图形时的属性栏: 在左栏的 PropertyManager 页 (见上面 leftPanel)

                // 测量结果: 浮在视图左上角
                MeasurePanel { anchors.left: parent.left; anchors.leftMargin: 12; anchors.top: parent.top; anchors.topMargin: 12 }
                // 仿真面板: 也在左上角
                SimPanel { anchors.left: parent.left; anchors.leftMargin: 12; anchors.top: parent.top; anchors.topMargin: 12 }

                // 参数面板: 浮在视图左上角
                FormPanel {
                    anchors.left: parent.left; anchors.leftMargin: 12
                    anchors.top: parent.top; anchors.topMargin: app.sketchActive ? 40 : 12
                    width: 300
                }

                Text {
                    anchors.top: parent.top; anchors.topMargin: 14
                    anchors.left: parent.left; anchors.leftMargin: 14
                    visible: app.sketchActive
                    text: qsTr("正在编辑　") + app.sketchTitle
                    color: Theme.cAccent
                    font.family: Theme.font; font.pixelSize: Theme.smallSize
                }

                // 左下角的坐标系: 跟着视角转
                AxisTriad {
                    anchors.left: parent.left; anchors.bottom: parent.bottom
                    anchors.leftMargin: 10; anchors.bottomMargin: 8
                    axes: viewport.axes
                }

                // 工程图: 一张图纸盖住三维视图 (连同上面那些三维用的小按钮)
                SheetView {
                    objectName: "sheetView"
                    anchors.fill: parent
                    visible: root.kind === "drawing"
                    dark: Theme.darkMode
                }
                Rectangle {                 // 标尺寸时下一步该点什么
                    anchors.top: parent.top; anchors.topMargin: 14
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: root.kind === "drawing" && sheetHint.text !== ""
                    width: sheetHint.implicitWidth + 28; height: 30; radius: 15
                    color: Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.92)
                    border.width: 1; border.color: Theme.cAccentLine
                    Text {
                        id: sheetHint
                        anchors.centerIn: parent
                        text: drawing.state.running ? qsTr("正在投影…") : drawing.state.hint
                        color: Theme.cText
                        font.family: Theme.font; font.pixelSize: Theme.smallSize
                    }
                }

                // 提示条: 出错原因等, 几秒后自己消失, 点一下立刻关掉
                Rectangle {
                    id: toast
                    property string text: ""
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom; anchors.bottomMargin: 36
                    width: Math.min(toastText.implicitWidth + 32, parent.width - 48)
                    height: toastText.implicitHeight + 20
                    radius: 8
                    color: Theme.cBgCard
                    border.width: 1; border.color: Theme.cDivider
                    visible: opacity > 0
                    opacity: 0
                    Behavior on opacity { NumberAnimation { duration: 160 } }
                    Text {
                        id: toastText
                        anchors.centerIn: parent
                        width: Math.min(implicitWidth, toast.parent.width - 80)
                        text: toast.text
                        wrapMode: Text.Wrap
                        color: Theme.cText
                        font.family: Theme.font; font.pixelSize: Theme.textSize
                    }
                    Timer { id: toastTimer; interval: 6000; onTriggered: toast.opacity = 0 }
                    MouseArea { anchors.fill: parent; onClicked: toast.opacity = 0 }
                    Connections {
                        target: app
                        function onNotice(text) { toast.text = app.tr(text); toast.opacity = 1; toastTimer.restart() }
                    }
                }
            }

        }

        // ================= 状态栏 =================
        StatusBar {}
    }

    // ================= 开始页: 刚打开软件先选新建哪一种 / 打开文件 (盖住标题栏下面的部分) =================
    StartPage {
        anchors.fill: parent
        anchors.topMargin: 38
        anchors.margins: root.maximized ? 0 : 1
        z: 800
        onOpenRequested: openDialog.open()
    }

    // 窗口描边 (没有系统边框了, 深色窗口叠在深色桌面上要有条边才分得开)
    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: root.maximized ? 0 : 1
        border.color: Theme.cDivider
        radius: root.maximized ? 0 : 8      // 和系统给窗口裁的圆角一致 (win32_frame.round_corners)
        z: 900
    }

    // 拖窗口边缘改大小 (8 个看不见的热区; 最大化时停用)
    component ResizeEdge: MouseArea {
        property int edges: 0
        z: 1000
        enabled: !root.maximized
        onPressed: root.startSystemResize(edges)
    }
    ResizeEdge { edges: Qt.LeftEdge; width: 5; height: parent.height; anchors.left: parent.left; cursorShape: Qt.SizeHorCursor }
    ResizeEdge { edges: Qt.RightEdge; width: 5; height: parent.height; anchors.right: parent.right; cursorShape: Qt.SizeHorCursor }
    ResizeEdge { edges: Qt.TopEdge; height: 4; width: parent.width; anchors.top: parent.top; cursorShape: Qt.SizeVerCursor }
    ResizeEdge { edges: Qt.BottomEdge; height: 5; width: parent.width; anchors.bottom: parent.bottom; cursorShape: Qt.SizeVerCursor }
    ResizeEdge { edges: Qt.TopEdge | Qt.LeftEdge; width: 10; height: 10; anchors.top: parent.top; anchors.left: parent.left; cursorShape: Qt.SizeFDiagCursor }
    ResizeEdge { edges: Qt.TopEdge | Qt.RightEdge; width: 10; height: 10; anchors.top: parent.top; anchors.right: parent.right; cursorShape: Qt.SizeBDiagCursor }
    ResizeEdge { edges: Qt.BottomEdge | Qt.LeftEdge; width: 10; height: 10; anchors.bottom: parent.bottom; anchors.left: parent.left; cursorShape: Qt.SizeBDiagCursor }
    ResizeEdge { edges: Qt.BottomEdge | Qt.RightEdge; width: 10; height: 10; anchors.bottom: parent.bottom; anchors.right: parent.right; cursorShape: Qt.SizeFDiagCursor }
}
