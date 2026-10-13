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
                    onActivated: app.runAction(modelData.id)
                }
            }
        }
    }
    Connections {
        target: app
        function onDialogRequested(which) {
            if (which === "open") openDialog.open()
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

    FileDialog {
        id: openDialog
        title: "打开零件"
        nameFilters: ["GenForm 零件 (*.gform)"]
        onAccepted: app.openDocument(selectedFile)
    }
    FileDialog {
        id: saveDialog
        title: "保存零件"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "gform"
        nameFilters: ["GenForm 零件 (*.gform)"]
        onAccepted: app.saveDocument(selectedFile)
    }
    FileDialog {
        id: exportDialog
        title: "导出"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "step"
        nameFilters: ["STEP 精确几何 (*.step *.stp)", "STL 三角网格 (*.stl)"]
        onAccepted: app.exportModel(selectedFile)
    }

    component Separator: Rectangle { width: 1; height: 34; color: Theme.cDivider; Layout.leftMargin: 6; Layout.rightMargin: 6 }
    component SectionTitle: Text {
        color: Theme.cTextMuted
        font.family: Theme.font; font.pixelSize: 11; font.bold: true
        Layout.leftMargin: 4
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ================= 标题栏 =================
        Rectangle {
            id: titleBar
            Layout.fillWidth: true
            height: 38
            color: Theme.cBgTitle

            // 拖动标题栏移动窗口, 双击最大化 / 还原。真的拖动了才开始移动: 不然最大化时单击一下窗口就缩回去
            MouseArea {
                anchors.fill: parent
                property point pressAt
                property bool moving: false
                onPressed: (mouse) => { pressAt = Qt.point(mouse.x, mouse.y); moving = false }
                onPositionChanged: (mouse) => {
                    if (!pressed || moving) return
                    const slop = Qt.styleHints.startDragDistance
                    if (Math.abs(mouse.x - pressAt.x) < slop && Math.abs(mouse.y - pressAt.y) < slop) return
                    moving = true
                    if (root.maximized) {
                        const at = titleBar.mapToGlobal(mouse.x, mouse.y)
                        const ratio = mouse.x / Math.max(1, titleBar.width)
                        root.showNormal()
                        root.x = Math.round(at.x - root.width * ratio)
                        root.y = Math.round(at.y - mouse.y)
                    }
                    root.startSystemMove()
                }
                onDoubleClicked: app.toggleMaximize()
            }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                spacing: 2
                Rectangle {                 // 标志: 一个蓝色小方块 + 名字
                    width: 16; height: 16; radius: 4
                    color: Theme.cAccentStrong
                    Rectangle { x: 4; y: 4; width: 8; height: 8; radius: 2; color: "transparent"; border.width: 1.5; border.color: "#FFFFFF" }
                    Layout.rightMargin: 6
                }
                Text {
                    text: "GenForm"
                    color: Theme.cText
                    font.family: Theme.font; font.pixelSize: 14; font.bold: true
                    Layout.rightMargin: 14
                }
                IconBtn { icon: "new"; tip: "新零件"; action: "file.new"; onClicked: app.runAction("file.new") }
                IconBtn { icon: "open"; tip: "打开零件"; action: "file.open"; onClicked: app.runAction("file.open") }
                IconBtn { icon: "save"; tip: "保存零件"; action: "file.save"; onClicked: app.runAction("file.save") }
                IconBtn { icon: "export"; tip: "导出：STEP 精确几何 / STL 三角网格"; action: "file.export"; onClicked: app.runAction("file.export") }
                Rectangle { width: 1; height: 18; color: Theme.cDivider; Layout.leftMargin: 6; Layout.rightMargin: 6 }
                IconBtn { icon: "undo"; tip: "撤销"; action: "edit.undo"; enabled: app.canUndo; onClicked: app.undo() }
                IconBtn { icon: "redo"; tip: "重做"; action: "edit.redo"; enabled: app.canRedo; onClicked: app.redo() }
                Item { Layout.fillWidth: true }
                IconBtn { icon: "gear"; tip: "设置：快捷键、鼠标笔势（右键手势轮）、AI 接口"; action: "app.settings"; onClicked: settingsDialog.open() }
                IconBtn { icon: "theme"; tip: Theme.darkMode ? "换成浅色界面" : "换成深色界面"; onClicked: Theme.darkMode = !Theme.darkMode }
                Item { width: 6 }
                IconBtn { icon: "min"; implicitWidth: 44; implicitHeight: 38; radius: 0; onClicked: root.showMinimized() }
                IconBtn { icon: root.maximized ? "restore" : "max"; implicitWidth: 44; implicitHeight: 38; radius: 0; onClicked: app.toggleMaximize() }
                IconBtn { icon: "close"; danger: true; implicitWidth: 44; implicitHeight: 38; radius: 0; onClicked: root.close() }
            }
            // 文档名放在正中 (不参与上面一行的排布, 所以不会被两边的按钮挤偏)
            Text {
                anchors.centerIn: parent
                text: app.title + (app.busy ? "　·　计算中…" : "")
                color: Theme.cTextSec
                font.family: Theme.font; font.pixelSize: Theme.smallSize
            }
        }

        // ================= 工具栏: 特征 / 草图 两页 (和 SOLIDWORKS 的命令管理器一样, 只是翻页, 不换界面) =================
        Rectangle {
            Layout.fillWidth: true
            height: 96
            color: Theme.cBg
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.cDivider }

            // ---- 特征页 (和 SOLIDWORKS 的特征页一个顺序: 凸台 | 切除和孔 | 修改 | 阵列、参考几何体、曲线) ----
            Flickable {
                id: featureRibbon
                x: 12; y: 6; height: 54
                width: parent.width - 24
                visible: app.tab === "feature"
                contentWidth: featureRow.implicitWidth; contentHeight: 54
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.HorizontalFlick
                interactive: contentWidth > width
                WheelHandler {
                    onWheel: (event) => featureRibbon.contentX = Math.max(0, Math.min(featureRibbon.contentWidth - featureRibbon.width,
                                                                                      featureRibbon.contentX - event.angleDelta.y))
                }
                RowLayout {
                    id: featureRow
                    height: 54
                    spacing: 1
                    RibbonBtn { icon: "extrude"; text: "拉伸凸台"; tip: "拉伸凸台/基体：把草图拉伸成实体。正在画草图时点它：先保存草图，接着就拉伸它"; action: "cmd:extrude"; onClicked: app.startCommand("extrude") }
                    RibbonBtn { icon: "revolve"; text: "旋转凸台"; tip: "旋转凸台/基体：把草图绕一根轴旋转成实体"; onClicked: app.startCommand("revolve") }
                    RibbonBtn { icon: "sweep"; text: "扫描"; tip: "让轮廓草图沿一条路径 (草图或曲线) 扫过去"; onClicked: app.startCommand("sweep") }
                    RibbonBtn { icon: "loft"; text: "放样凸台"; tip: "放样凸台/基体：在几个草图轮廓之间过渡"; onClicked: app.startCommand("loft") }
                    RibbonBtn { icon: "boundary"; text: "边界凸台"; tip: "边界凸台/基体：轮廓之间光顺过渡 (目前只有方向 1)"; onClicked: app.startCommand("boundary") }
                    Separator {}
                    RibbonBtn { icon: "cut"; text: "拉伸切除"; tip: "用草图从实体上切掉一块"; onClicked: app.startCommand("cut") }
                    RibbonMenu { icon: "hole"; text: "异形孔"; tip: "异形孔向导、高级孔、螺纹线、螺柱向导"; items: app.featureMenus[0].items; onPicked: (id) => app.startCommand(id) }
                    RibbonBtn { icon: "revolve"; text: "旋转切除"; tip: "把草图绕轴旋转, 从实体上切掉"; onClicked: app.startCommand("revolve_cut") }
                    RibbonBtn { icon: "sweep"; text: "扫描切除"; tip: "轮廓沿路径扫过去, 从实体上切掉"; onClicked: app.startCommand("sweep_cut") }
                    RibbonBtn { icon: "loft"; text: "放样切除"; tip: "在几个轮廓之间过渡, 从实体上切掉"; onClicked: app.startCommand("loft_cut") }
                    Separator {}
                    RibbonBtn { icon: "fillet"; text: "圆角"; tip: "圆角：给选中的边倒圆角"; action: "cmd:fillet"; onClicked: app.startCommand("fillet") }
                    RibbonBtn { icon: "chamfer"; text: "倒角"; tip: "给选中的边倒斜角"; onClicked: app.startCommand("chamfer") }
                    RibbonBtn { icon: "rib"; text: "筋"; tip: "用一条开口的草图线做加强筋"; onClicked: app.startCommand("rib") }
                    RibbonBtn { icon: "draft"; text: "拔模"; tip: "把选中的面相对中性面倾斜一个角度"; onClicked: app.startCommand("draft") }
                    RibbonBtn { icon: "shell"; text: "抽壳"; tip: "掏空成等厚的壳, 选中的面成为开口"; onClicked: app.startCommand("shell") }
                    RibbonBtn { icon: "wrap"; text: "包裹"; tip: "把草图轮廓贴到圆柱面上, 凸起或凹进"; onClicked: app.startCommand("wrap") }
                    RibbonBtn { icon: "mirror"; text: "镜像"; tip: "关于一个基准面镜像特征或整个实体"; onClicked: app.startCommand("mirror") }
                    Separator {}
                    RibbonMenu { icon: "pattern"; text: "阵列"; tip: "线性、圆周、镜像、曲线驱动、草图驱动、表格驱动、填充、变量阵列"; items: app.featureMenus[1].items; onPicked: (id) => app.startCommand(id) }
                    RibbonMenu { icon: "reference"; text: "参考几何体"; tip: "基准面、基准轴、坐标系、点、质心、边界框"; items: app.featureMenus[2].items; onPicked: (id) => app.startCommand(id) }
                    RibbonMenu { icon: "curve"; text: "曲线"; tip: "分割线、投影曲线、组合曲线、通过点的曲线、螺旋线/涡状线"; items: app.featureMenus[3].items; onPicked: (id) => app.startCommand(id) }
                }
            }

            // ---- 草图页 (工具多, 窗口窄时可以左右滚) ----
            Flickable {
                id: sketchRibbon
                x: 12; y: 6; height: 54
                width: parent.width - 24
                visible: app.tab === "sketch"
                contentWidth: sketchRow.implicitWidth; contentHeight: 54
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                flickableDirection: Flickable.HorizontalFlick
                interactive: contentWidth > width
                WheelHandler {
                    onWheel: (event) => sketchRibbon.contentX = Math.max(0, Math.min(sketchRibbon.contentWidth - sketchRibbon.width,
                                                                                    sketchRibbon.contentX - event.angleDelta.y))
                }
                RowLayout {
                    id: sketchRow
                    height: 54
                    spacing: 1
                    RibbonBtn {
                        icon: app.sketchActive ? "exit" : "sketch"
                        text: app.sketchActive ? "退出草图" : "草图绘制"
                        active: app.sketchActive
                        tip: app.sketchActive ? "退出草图：保存这个草图并退出" : "草图绘制：选一个基准面开始画草图"
                        action: app.sketchActive ? "sketch.finish" : "sketch.start"
                        onClicked: app.startSketch()
                    }
                    Separator {}
                    RibbonBtn { enabled: app.sketchActive; icon: "dimension"; text: "智能尺寸"; tip: "智能尺寸：点一个图形改它的尺寸；再点另一个图形 = 改它们之间的距离"; action: "tool:dimension"; active: app.sketchTool === "dimension"; onClicked: app.useSketchTool("dimension") }
                    Separator {}
                    RibbonMenu {
                        icon: "line"; text: "直线"; tip: "直线：直线、中心线、中点线"; action: "tool:line"
                        active: ["line", "centerline", "midline"].indexOf(app.sketchTool) >= 0
                        items: [{id: "line", title: "直线"}, {id: "centerline", title: "中心线"}, {id: "midline", title: "中点线"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonMenu {
                        icon: "rect"; text: "矩形"; tip: "矩形：边角矩形、中心矩形、3 点边角矩形、3 点中心矩形、平行四边形、多边形"; action: "tool:rect"
                        active: ["rect", "crect", "rect3", "crect3", "pgram", "ngon"].indexOf(app.sketchTool) >= 0
                        items: [{id: "rect", title: "边角矩形"}, {id: "crect", title: "中心矩形"}, {id: "rect3", title: "3 点边角矩形"},
                                {id: "crect3", title: "3 点中心矩形"}, {id: "pgram", title: "平行四边形"}, {id: "ngon", title: "多边形"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonMenu {
                        icon: "slot"; text: "槽口"; tip: "直槽口、中心点直槽口、三点圆弧槽口、中心点圆弧槽口"
                        active: ["slot", "cslot", "aslot3", "caslot"].indexOf(app.sketchTool) >= 0
                        items: [{id: "slot", title: "直槽口"}, {id: "cslot", title: "中心点直槽口"}, {id: "aslot3", title: "三点圆弧槽口"},
                                {id: "caslot", title: "中心点圆弧槽口"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonMenu {
                        icon: "circle"; text: "圆"; tip: "圆：圆心 + 半径；周边圆：圆周上三个点；椭圆：中心 → 长轴 → 短轴"; action: "tool:circle"
                        active: ["circle", "circle3", "ellipse"].indexOf(app.sketchTool) >= 0
                        items: [{id: "circle", title: "圆"}, {id: "circle3", title: "周边圆"}, {id: "ellipse", title: "椭圆"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonBtn { icon: "arc"; text: "圆弧"; tip: "圆弧：圆心/起/终点画弧"; action: "tool:arc"; active: app.sketchTool === "arc"; onClicked: app.useSketchTool("arc") }
                    RibbonMenu {
                        icon: "spline"; text: "样条"; tip: "样条曲线、样式样条曲线、方程式驱动的曲线"
                        active: ["spline", "sspline", "equation"].indexOf(app.sketchTool) >= 0
                        items: [{id: "spline", title: "样条曲线"}, {id: "sspline", title: "样式样条曲线"}, {id: "equation", title: "方程式驱动的曲线"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonBtn { icon: "point"; text: "点"; tip: "绘制一个点：单击放置"; active: app.sketchTool === "point"; onClicked: app.useSketchTool("point") }
                    RibbonBtn { icon: "text"; text: "文本"; tip: "单击放置一行字；先选中一条曲线再点这里 = 沿这条曲线排"; active: app.sketchTool === "text"; onClicked: app.useSketchTool("text") }
                    Separator {}
                    RibbonBtn { enabled: app.sketchActive; icon: "fillet"; text: "圆角"; tip: "绘制圆角：点两条直线相交的尖角"; active: app.sketchTool === "fillet"; onClicked: app.useSketchTool("fillet") }
                    RibbonMenu {
                        enabled: app.sketchActive
                        icon: "trim"; text: "剪裁"; tip: "剪裁实体：点要剪掉的那一段；延伸实体：点要延长的那一头"; action: "tool:trim"
                        active: ["trim", "extend"].indexOf(app.sketchTool) >= 0
                        items: [{id: "trim", title: "剪裁实体"}, {id: "extend", title: "延伸实体"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonBtn { enabled: app.sketchActive; icon: "offset"; text: "等距"; tip: "等距实体：点一个图形，再点一下定距离和方向"; action: "tool:offset"; active: app.sketchTool === "offset"; onClicked: app.useSketchTool("offset") }
                    RibbonBtn { enabled: app.sketchActive; icon: "mirror"; text: "镜向"; tip: "镜向实体：先选图形，再点两点定镜向轴"; active: app.sketchTool === "mirror"; onClicked: app.useSketchTool("mirror") }
                    RibbonMenu {
                        enabled: app.sketchActive
                        icon: "pattern"; text: "阵列"; tip: "先选图形。线性草图阵列：填数量和间距；圆周草图阵列：填数量、总角度和中心"
                        active: app.sketchOperation === "pattern" || app.sketchOperation === "cpattern"
                        items: [{id: "pattern", title: "线性草图阵列"}, {id: "cpattern", title: "圆周草图阵列"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonBtn { enabled: app.sketchActive; icon: "move"; text: "移动"; tip: "移动实体：先选图形，再点起点和终点"; action: "tool:move"; active: app.sketchTool === "move"; onClicked: app.useSketchTool("move") }
                    RibbonMenu {
                        enabled: app.sketchActive
                        icon: "convert"; text: "转换引用"; tip: "转换实体引用：把实体的边拷进草图；侧影实体：曲面转过去的轮廓线；交叉曲线：草图平面切开实体的交线"
                        active: app.sketchTool === "convert"
                        items: [{id: "convert", title: "转换实体引用"}, {id: "silhouette", title: "侧影实体"}, {id: "section", title: "交叉曲线"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    Separator {}
                    RibbonMenu {
                        enabled: app.sketchActive
                        icon: "relation"; text: "几何关系"; tip: "添加几何关系：先选图形（第一个不动），再选水平 / 竖直 / 平行 / 垂直 / 相等 / 同心 / 相切…；修复草图：找出废线、重复的线、没接上的端点"
                        active: app.sketchOperation === "relation" || app.sketchOperation === "repair"
                        items: [{id: "relation", title: "添加几何关系"}, {id: "repair", title: "修复草图"}]
                        onPicked: (id) => app.sketchPick(id)
                    }
                    RibbonBtn {
                        id: snapButton
                        icon: "snap"; text: "捕捉"
                        tip: "捕捉：每一种可以单独开关；右边一列是快速捕捉（下一次点击只吸到这一种点）"
                        active: app.quickSnap !== ""
                        onClicked: snapMenu.opened ? snapMenu.close() : snapMenu.open()
                        Popup {
                            id: snapMenu
                            y: parent.height + 6
                            padding: 8
                            onAboutToShow: x = Math.min(0, root.width - 8 - snapButton.mapToItem(null, 0, 0).x - implicitWidth)
                            background: Rectangle { color: Theme.cBg; radius: 8; border.width: 1; border.color: Theme.cDivider }
                            contentItem: Row {
                                spacing: 8
                                Column {
                                    spacing: 2
                                    Text { x: 8; height: 24; verticalAlignment: Text.AlignVCenter; text: "一直开着"; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.textSize - 1 }
                                    Repeater {
                                        model: app.snapToggles
                                        delegate: Rectangle {
                                            required property var modelData
                                            width: 150; height: 30; radius: 5
                                            color: toggleArea.containsMouse ? Theme.cBgHover : "transparent"
                                            Text {
                                                anchors.verticalCenter: parent.verticalCenter
                                                x: 10; width: 16
                                                text: modelData.on ? "✓" : ""
                                                color: Theme.cAccent
                                                font.family: Theme.font; font.pixelSize: Theme.textSize
                                            }
                                            Text {
                                                anchors.verticalCenter: parent.verticalCenter
                                                x: 30
                                                text: modelData.text
                                                color: modelData.on ? Theme.cText : Theme.cTextMuted
                                                font.family: Theme.font; font.pixelSize: Theme.textSize
                                            }
                                            MouseArea {
                                                id: toggleArea
                                                anchors.fill: parent; hoverEnabled: true
                                                onClicked: app.toggleSnap(modelData.id)
                                            }
                                        }
                                    }
                                }
                                Rectangle { width: 1; height: parent.height; color: Theme.cDivider }
                                Column {
                                    spacing: 2
                                    Text { x: 8; height: 24; verticalAlignment: Text.AlignVCenter; text: "只用一次"; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.textSize - 1 }
                                    Repeater {
                                        model: app.quickSnaps
                                        delegate: Rectangle {
                                            required property var modelData
                                            readonly property bool on: app.quickSnap === modelData.id
                                            width: 138; height: 30; radius: 5
                                            opacity: app.sketchActive ? 1 : 0.45
                                            color: on ? Theme.cAccentSoft : (snapArea.containsMouse ? Theme.cBgHover : "transparent")
                                            Text {
                                                anchors.verticalCenter: parent.verticalCenter
                                                x: 12
                                                text: modelData.text
                                                color: parent.on ? Theme.cAccent : Theme.cText
                                                font.family: Theme.font; font.pixelSize: Theme.textSize
                                            }
                                            MouseArea {
                                                id: snapArea
                                                anchors.fill: parent; hoverEnabled: true
                                                onClicked: { app.setQuickSnap(modelData.id); snapMenu.close() }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    RibbonMenu { icon: "sketch3d"; text: "3D 草图"; tip: "3D 草图：按空间坐标点连成的线；曲面上的样条曲线：贴在一张面上的样条"; items: app.featureMenus[4].items; onPicked: (id) => app.startCommand(id) }
                    RibbonBtn { icon: "rapid"; text: "快速草图"; tip: "快速草图：进草图不转视角，画完一个接着点下一个基准面"; active: app.rapidSketch; onClicked: app.toggleRapidSketch() }
                    Separator { visible: app.sketchActive }
                    RibbonBtn { visible: app.sketchActive; icon: "select"; text: "选择"; tip: "选择：选中、移动、改形状（按 Esc 也回到这里）"; active: app.sketchTool === "select" && app.sketchOperation === ""; onClicked: app.useSketchTool("select") }
                }
            }

            // ---- 页签 ----
            Row {
                x: 12
                anchors.bottom: parent.bottom; anchors.bottomMargin: 6
                spacing: 4
                Repeater {
                    model: [{ id: "feature", text: "特征" }, { id: "sketch", text: "草图" }]
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
            }
        }

        // ================= 主体 =================
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            // ---- 左: 基准面 + 特征历史 ----
            Rectangle {
                Layout.preferredWidth: 264
                Layout.fillHeight: true
                color: Theme.cBg
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    anchors.topMargin: 12
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 6
                        Rectangle { width: 3; height: 12; radius: 1.5; color: Theme.cAccent; Layout.leftMargin: 4 }
                        Text { text: "设计树"; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
                        Item { Layout.fillWidth: true }
                    }
                    DesignTree { Layout.fillWidth: true; Layout.fillHeight: true }
                    Rectangle {                 // 实体的大小: 一张小卡片
                        Layout.fillWidth: true
                        implicitHeight: bodyInfo.implicitHeight + 18
                        radius: 8
                        color: Theme.cBgCard
                        border.width: 1; border.color: Theme.cDivider
                        Text {
                            id: bodyInfo
                            x: 12; y: 9
                            width: parent.width - 24
                            text: app.bodyText
                            wrapMode: Text.Wrap
                            lineHeight: 1.35
                            color: Theme.cTextSec
                            font.family: Theme.font; font.pixelSize: Theme.smallSize
                        }
                    }
                }
                Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.cDivider }
            }

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
                    dark: Theme.darkMode
                }

                // 视图里的文字: 基准面的名字、草图的尺寸
                Repeater {
                    model: viewport.labels
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool size: modelData.kind === "size"
                        x: modelData.x; y: modelData.y
                        width: labelText.implicitWidth + (size ? 12 : 0)
                        height: labelText.implicitHeight + (size ? 6 : 0)
                        radius: 4
                        color: size ? Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.88) : "transparent"
                        border.width: size ? 1 : 0
                        border.color: Theme.cDivider
                        Text {
                            id: labelText
                            anchors.centerIn: parent
                            text: modelData.text
                            color: size ? Theme.cText : Theme.cAccent
                            opacity: size ? 1.0 : 0.85
                            font.family: Theme.font; font.pixelSize: size ? Theme.smallSize : 11
                        }
                    }
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
                        model: [{ icon: "finish", tint: "#3FB97F", tip: "完成草图：保存并退出" },
                                { icon: "cancel", tint: "#E5484D", tip: "放弃：不保存这次画的，退出草图" }]
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: 44; height: 44; radius: 22
                            color: cornerArea.containsMouse ? modelData.tint : Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.88)
                            border.width: 1.5; border.color: modelData.tint
                            Icon { anchors.centerIn: parent; size: 24; name: modelData.icon; color: cornerArea.containsMouse ? "#FFFFFF" : modelData.tint }
                            MouseArea {
                                id: cornerArea
                                anchors.fill: parent; hoverEnabled: true
                                onClicked: index === 0 ? app.finishSketch() : app.cancelSketch()
                            }
                            Tip { shown: cornerArea.containsMouse; text: modelData.tip }
                        }
                    }
                }
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
                    text: "正在编辑　" + app.sketchTitle
                    color: Theme.cAccent
                    font.family: Theme.font; font.pixelSize: Theme.smallSize
                }

                // 左下角的坐标系: 跟着视角转
                AxisTriad {
                    anchors.left: parent.left; anchors.bottom: parent.bottom
                    anchors.leftMargin: 10; anchors.bottomMargin: 8
                    axes: viewport.axes
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
                        function onNotice(text) { toast.text = text; toast.opacity = 1; toastTimer.restart() }
                    }
                }
            }

        }

        // ================= 状态栏 =================
        Rectangle {
            Layout.fillWidth: true
            height: 26
            color: Theme.cBgTitle
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14; anchors.rightMargin: 14
                Text {
                    text: app.hoverText !== "" ? app.hoverText : app.selectionText
                    color: Theme.cTextSec
                    font.family: Theme.font; font.pixelSize: Theme.smallSize
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
                Text {
                    text: (app.sketchActive ? "左键 画 / 选" : "左键 选择（Ctrl 多选，拖动框选）")
                          + "　·　中键 旋转　·　Ctrl+中键 平移　·　滚轮 缩放　·　右键拖动 手势轮"
                    color: Theme.cTextMuted
                    font.family: Theme.font; font.pixelSize: 11
                    visible: root.width > 1180
                }
                Rectangle { width: 1; height: 12; color: Theme.cDivider; Layout.leftMargin: 8; Layout.rightMargin: 8; visible: root.width > 1180 }
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.cAccent }
                Text {
                    text: apiText
                    color: Theme.cTextMuted
                    font.family: Theme.font; font.pixelSize: Theme.smallSize
                }
            }
        }
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
