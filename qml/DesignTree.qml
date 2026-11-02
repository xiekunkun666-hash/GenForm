// DesignTree.qml - 设计树: 零件 → 基准面 / 原点 → 特征 (草图收在用它的拉伸下面) → 回退线。
// 单击选中, 双击基准面 = 在它上面画草图, 双击特征 = 编辑它; 悬停特征出现 抑制 / 删除。
// 右键特征: 菜单 (重命名、编辑、压缩、退回、隐藏、孤立、删除…)。重命名是在那一行上弹一个输入框, 回车确定, Esc 取消。
// 右键零件 (第一行)、材质、基准面、原点也有各自的菜单 (app.treeMenu)。
// 出错的特征标红并写明原因; 正在编辑的草图标蓝。
// 回退线: 蓝色的横条, 上下拖到两个特征之间 — 它下面的特征暂不计算 (变淡); 双击它 = 回到最后。
// 点基准面: 旁边浮出一排小按钮 (草图绘制 / 显示隐藏 / 放大所选范围 / 正视于)。点 "材质": 选材质。
// 点特征或草图: 浮出它的小工具条 (编辑特征 / 编辑草图 / 压缩 / 退回 / 隐藏显示 / 放大所选范围 / 正视于 / 外观…)。
import QtQuick
import QtQuick.Controls

ListView {
    id: list
    clip: true
    spacing: 2
    model: app.tree
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    property bool rolling: false        // 正在拖回退线
    property real keptY: -1             // 换内容之前滚到哪了 (换模型 ListView 会跳回顶上: 换完滚回去)
    readonly property string contextMode: app.docKind + ":" + app.sketchActive + ":" + app.pickingPlane
    onContextModeChanged: {
        if (planeBar) { planeBar.close(); planeBar.plane = "" }
        if (featureBar) { featureBar.close(); featureBar.target = ""; featureBar.items = [] }
        if (rowMenu) { rowMenu.close(); rowMenu.target = "" }
        if (renameBox) renameBox.close()
        if (materialMenu) materialMenu.close()
    }

    Connections {
        target: app
        function onTreeAboutToChange() { list.keptY = list.contentY }
    }
    property string shownSelection: ""  // 上一次滚到眼前的选中特征: 选中换了 (视图里点的) 才滚过去, 不然留在用户滚到的地方
    onModelChanged: {
        const y = keptY
        keptY = -1
        if (y >= 0) list.contentY = y
        Qt.callLater(() => {
            if (y >= 0) list.contentY = Math.max(list.originY, Math.min(y, list.originY + list.contentHeight - list.height))
            const rows = app.tree
            let index = -1
            for (let i = 0; i < rows.length; i++)
                if (rows[i].kind === "feature" && rows[i].selected && rows[i].id !== "") { index = i; break }
            const id = index >= 0 ? rows[index].id : ""
            if (id !== shownSelection) {
                shownSelection = id
                if (index >= 0) list.positionViewAtIndex(index, ListView.Contain)
            }
        })
    }
    property real dropY: 0              // 松手会落在哪条缝上 (列表里的 y)
    property int dropCount: -1          // 落在那里 = 只算前几个特征

    // 光标在列表里的 y → 最近的那条 "缝" (两行之间)
    function aim(y) {
        let best = null
        const rows = list.contentItem.children
        for (let i = 0; i < rows.length; i++) {
            const item = rows[i]
            if (!item.modelData || item.modelData.kind !== "feature" || item.modelData.id === "") continue
            const top = item.y - list.contentY, bottom = top + item.height
            const seams = [[bottom, item.modelData.after]]
            if (item.modelData.before >= 0) seams.push([top, item.modelData.before])
            for (const seam of seams)
                if (best === null || Math.abs(seam[0] - y) < Math.abs(best[0] - y)) best = seam
        }
        if (best !== null) { list.dropY = best[0]; list.dropCount = best[1] }
    }

    // 点了基准面这一行。选中会让整棵树重新生成 (这一行跟着没了), 所以这段逻辑放在列表上, 不放在行里
    function planeTapped(plane, shown, below) {
        const picking = app.pickingPlane
        app.selectPlane(plane)
        if (picking || app.sketchActive) return
        planeBar.plane = plane
        planeBar.shown = shown
        planeBar.x = 30
        planeBar.y = below
        planeBar.open()
    }

    // 点了特征这一行: 选中它, 在它下面弹出小工具条 (和上面一样, 逻辑放在列表上)
    function featureTapped(identifier, below) {
        app.selectFeature(identifier)
        if (app.sketchActive || app.pickingPlane) return
        const items = app.featureContext(identifier)
        if (items.length === 0) return
        featureBar.target = identifier
        featureBar.items = items
        featureBar.x = 30
        featureBar.y = below
        featureBar.open()
    }

    ContextBar { id: featureBar; objectName: "designFeatureBar" }

    // 右键一行: 弹菜单。特征有自己的一套; 零件 (第一行)、材质、基准面、原点用 treeMenu
    function rowMenuAt(kind, identifier, x, top, below) {
        featureBar.close()
        planeBar.close()
        if ((app.sketchActive || app.pickingPlane) && kind !== "plane") return
        let items
        if (kind === "feature") {
            app.selectFeature(identifier)
            items = app.featureMenu(identifier)
        } else items = app.treeMenu(kind, identifier)
        if (items.length === 0) return
        rowMenu.kind = kind
        rowMenu.target = identifier
        rowMenu.rowTop = top
        rowMenu.below = below
        rowMenu.items = items
        rowMenu.x = Math.max(8, Math.min(list.width - 60, x))
        rowMenu.y = below
        rowMenu.open()
    }
    MenuList {
        id: rowMenu
        property string kind: ""
        property string target: ""
        property real rowTop: 0
        property real below: 0
        itemWidth: 190
        onPicked: (id) => {
            if (kind !== "feature") {
                if (id === "material") { materialMenu.x = 30; materialMenu.y = below; materialMenu.open() }
                else app.treeAction(kind, target, id)
            } else if (id === "rename") {
                renameBox.target = target
                renameBox.y = rowTop
                renameBox.open()
            } else if (id === "delete") app.deleteFeature(target)
            else app.contextAction(target, id)
        }
    }
    Popup {                             // 重命名: 盖在那一行上的输入框
        id: renameBox
        property string target: ""
        x: 30
        width: Math.max(140, list.width - 40); height: 30
        padding: 0
        background: Rectangle { color: Theme.cBgInput; radius: 6; border.width: 1; border.color: Theme.cAccent }
        onOpened: { nameInput.text = app.featureName(target); nameInput.selectAll(); nameInput.forceActiveFocus() }
        contentItem: TextInput {
            id: nameInput
            leftPadding: 8; rightPadding: 8
            verticalAlignment: TextInput.AlignVCenter
            color: Theme.cText
            selectionColor: Theme.cAccentStrong
            font.family: Theme.font; font.pixelSize: Theme.textSize
            selectByMouse: true
            clip: true
            onAccepted: { app.renameFeature(renameBox.target, text); renameBox.close() }
            Keys.onEscapePressed: renameBox.close()
        }
    }

    function popAt(popup, item) {       // 把浮窗摆到这一行的下面
        popup.x = 30
        popup.y = item.y - list.contentY + item.height + 2
        popup.open()
    }

    MenuList {
        id: materialMenu
        items: app.materialList
        itemWidth: 236
        onPicked: (id) => app.setMaterial(id)
    }
    Popup {                             // 基准面的浮动工具条
        id: planeBar
        objectName: "designPlaneBar"
        property string plane: ""
        property bool shown: false
        padding: 4
        background: Rectangle { color: Theme.cBgCard; radius: 9; border.width: 1; border.color: Theme.cDivider }
        contentItem: Row {
            spacing: 2
            IconBtn { icon: "sketch"; iconSize: 19; tip: qsTr("草图绘制：在这个基准面上画草图"); onClicked: { planeBar.close(); app.planeAction(planeBar.plane, "sketch") } }
            IconBtn { icon: planeBar.shown ? "eye_off" : "eye"; iconSize: 19; tip: planeBar.shown ? qsTr("隐藏这个基准面") : qsTr("显示这个基准面"); onClicked: { planeBar.shown = !planeBar.shown; app.planeAction(planeBar.plane, "toggle") } }
            IconBtn { icon: "zoom_sel"; iconSize: 19; tip: qsTr("放大所选范围：把这个基准面放满画面"); onClicked: app.planeAction(planeBar.plane, "zoom") }
            IconBtn { icon: "normal"; iconSize: 19; tip: qsTr("正视于：把视角转到正对这个基准面"); onClicked: app.planeAction(planeBar.plane, "normal") }
        }
    }

    Rectangle {                         // 拖的时候: 松手会落在这里
        z: 20
        visible: list.rolling && list.dropCount >= 0
        x: 6; y: list.dropY - 1
        width: list.width - 12; height: 2; radius: 1
        color: Theme.cAccent
    }

    // 层次: 零件 (第一行, 粗一号) → 参考 (材质、基准面、原点: 字和图标淡一档) → 分隔线 → 特征
    // (实体特征亮, 草图 / 曲线这些线条特征淡一档) → 收在特征下面的草图 (连线接回上一行)
    // 文件夹一层一种颜色 (Theme.levelColor, 像代码编辑器里的彩色括号): 文件夹的图标、箭头、名字, 和它里面每一行
    // 左边那道缩进竖线都是这一层的颜色, 一眼看得出哪几行属于哪个文件夹
    delegate: Rectangle {
        id: row
        objectName: modelData.kind === "plane" ? "designPlane_" + modelData.id : ""
        required property var modelData
        readonly property bool bar: modelData.kind === "rollback"
        readonly property bool feature: modelData.kind === "feature"
        readonly property bool folder: modelData.kind === "folder"
        readonly property color tone: Theme.levelColor((modelData.depth || 1) - 1)        // 文件夹这一层的颜色
        readonly property bool root: modelData.kind === "root"
        readonly property bool reference: ["material", "plane", "origin"].indexOf(modelData.kind) >= 0
        readonly property bool quiet: reference || (feature && modelData.line === true)     // 淡一档的行
        readonly property bool failed: modelData.state === "error"
        readonly property bool dim: modelData.suppressed || modelData.rolled || modelData.state === "skipped"
        readonly property bool chosen: (modelData.selected || modelData.editing) && !bar
        readonly property real indent: 6 + modelData.depth * 18
        readonly property real gap: modelData.kind === "origin" ? 11 : 0     // 原点下面: 分隔线, 和特征隔开
        readonly property real body: root ? 32 : reference ? 26 : Math.max(28, column.implicitHeight + 8)
        width: list.width
        height: bar ? 14 : body + gap
        color: "transparent"

        Rectangle {                         // 行底色 (不含下面的分隔线)
            width: parent.width; height: row.body
            visible: !row.bar
            radius: 6
            color: row.failed ? Theme.cErrorSoft
                 : row.chosen ? Theme.cAccentSoft
                 : hover.hovered ? Theme.cBgHover : "transparent"
            Rectangle {                     // 选中: 左边一道蓝条 (比整圈描边安静)
                visible: row.chosen
                x: 0; y: 5; width: 3; height: parent.height - 10; radius: 1.5
                color: Theme.cAccent
            }
        }
        Rectangle {                         // 参考和特征之间的分隔线
            visible: row.gap > 0
            x: 12; y: row.body + row.gap / 2
            width: parent.width - 24; height: 1
            color: Theme.cDivider
        }
        Rectangle {                         // 收在特征下面的草图: 一道竖线 + 一小横, 接回上一行的图标
            visible: row.modelData.child === true && !row.bar
            x: row.indent - 18 + 24; y: -1
            width: 1; height: row.body / 2 + 1
            color: Theme.cDivider
            Rectangle { x: 0; y: parent.height - 1; width: 7; height: 1; color: Theme.cDivider }
        }
        Repeater {                          // 套着的每一层文件夹一道竖线, 颜色跟那一层的文件夹一样
            model: row.bar ? 0 : (row.modelData.folders || 0)
            Rectangle {
                required property int index
                x: 6 + (index + 1) * 18 + 5; y: 0
                width: 2; height: row.height; radius: 1
                color: Theme.levelColor(index)
                opacity: row.dim ? 0.25 : 0.55
            }
        }

        HoverHandler { id: hover; enabled: !row.bar }
        TapHandler {                        // 右键: 菜单
            enabled: !row.bar && !row.folder && (!row.feature || row.modelData.id !== "")
            acceptedButtons: Qt.RightButton
            onTapped: (point) => list.rowMenuAt(row.modelData.kind, row.modelData.id, point.position.x,
                                                row.y - list.contentY, row.y - list.contentY + row.body + 2)
        }
        TapHandler {
            enabled: !row.bar
            onTapped: (point) => {
                if (row.folder) { if (point.position.x > row.indent + 13) app.toggleExpand(row.modelData.id) }    // 箭头自己会切换
                else if (row.modelData.kind === "plane") list.planeTapped(row.modelData.id, row.modelData.shown, row.y - list.contentY + row.height + 2)
                else if (row.modelData.kind === "material") list.popAt(materialMenu, row)
                else if (row.feature && row.modelData.id !== "") {
                    if (actions.active && point.position.x >= actions.x) return         // 点的是右边的 抑制 / 删除
                    list.featureTapped(row.modelData.id, row.y - list.contentY + row.height + 2)
                }
            }
            onDoubleTapped: {
                if (row.modelData.kind === "plane") app.sketchOn(row.modelData.id)
                else if (row.feature && row.modelData.id !== "") { featureBar.close(); app.editFeature(row.modelData.id) }
            }
        }

        // ---- 回退线 ----
        Item {
            anchors.fill: parent
            visible: row.bar
            readonly property bool back: row.bar && row.modelData.count < row.modelData.total     // 现在确实退回去了
            opacity: list.rolling ? 0.35 : 1.0
            Rectangle {                 // 横条
                anchors.verticalCenter: parent.verticalCenter
                x: 8; width: parent.width - 16; height: barArea.containsMouse || parent.back ? 3 : 2; radius: 1.5
                color: Theme.cAccent
                opacity: parent.back || barArea.containsMouse ? 1.0 : 0.55
            }
            Rectangle {                 // 左边的把手
                anchors.verticalCenter: parent.verticalCenter
                x: 8; width: 16; height: 8; radius: 4
                color: Theme.cAccent
            }
            MouseArea {
                id: barArea
                anchors.fill: parent
                anchors.topMargin: -4; anchors.bottomMargin: -4
                hoverEnabled: true
                enabled: !app.sketchActive
                cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor      // 一只手: 张开 = 可以捏住, 握住 = 正拖着
                preventStealing: true
                onPressed: (mouse) => { list.rolling = true; list.dropCount = -1; list.aim(mapToItem(list, mouse.x, mouse.y).y) }
                onPositionChanged: (mouse) => { if (pressed) list.aim(mapToItem(list, mouse.x, mouse.y).y) }
                onReleased: {
                    const count = list.dropCount, total = row.modelData.total
                    list.rolling = false
                    if (count >= 0 && count !== row.modelData.count) app.rollbackTo(count >= total ? -1 : count)
                }
                onCanceled: list.rolling = false
                onDoubleClicked: { list.rolling = false; app.rollbackTo(-1) }
                Tip { shown: barArea.containsMouse && !barArea.pressed; text: qsTr("回退线：捏住上下拖到两个特征之间，它下面的特征暂不计算；双击回到最后") }
            }
        }

        // 展开 / 收起 (下面收着草图的拉伸才有)
        Item {
            x: row.indent - 3; y: (row.body - height) / 2
            width: 16; height: 20
            visible: row.modelData.expandable && !row.bar
            Icon {
                anchors.centerIn: parent
                size: 14
                name: "tree_chevron"
                rotation: row.modelData.expanded ? 90 : 0
                Behavior on rotation { NumberAnimation { duration: 120 } }
                color: row.folder ? row.tone : chevronHover.hovered ? Theme.cText : Theme.cTextMuted
            }
            HoverHandler { id: chevronHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: app.toggleExpand(row.modelData.id) }
        }

        // 节点图标
        Item {
            id: glyph
            x: row.indent + 14; y: row.reference || row.root ? (row.body - height) / 2 : 4
            width: 20; height: 20
            visible: !row.bar
            opacity: row.dim ? 0.35 : (row.modelData.hidden === true ? 0.5 : 1.0)      // 隐藏着的淡一点
            Icon {                          // 特征: 和工具栏上同一个图标 (出错的是红的)
                anchors.centerIn: parent
                visible: row.feature
                size: 19
                name: row.feature ? (row.modelData.icon || row.modelData.type) : ""
                color: row.failed ? Theme.cError : row.chosen ? Theme.cAccent : row.quiet ? Theme.cTextSec : Theme.cIcon
            }
            Icon {
                anchors.centerIn: parent
                visible: !row.feature
                size: row.root ? 19 : row.folder ? 18 : 16
                name: row.folder ? (row.modelData.expanded ? "folder_open" : "folder")
                    : row.modelData.kind === "plane" ? "plane" : row.modelData.kind === "origin" ? "origin"
                    : row.modelData.kind === "material" ? "material" : "part"
                color: row.folder ? (row.failed ? Theme.cError : row.tone) : row.root || row.chosen ? Theme.cAccent : Theme.cTextMuted
                opacity: row.modelData.kind === "plane" && !row.modelData.shown && !row.modelData.selected ? 0.5 : 1.0    // 没显示着的基准面淡一点
            }
        }

        // 加工工艺徽标 (评估 → 绑定工艺之后): 工艺的简称, 底色是工艺的颜色; 悬停看全名、为什么选它、备选
        Rectangle {
            id: badge
            anchors.left: glyph.right; anchors.leftMargin: visible ? 6 : 0
            y: 4 + (20 - height) / 2
            visible: row.feature && (row.modelData.process || "") !== ""
            width: visible ? badgeText.implicitWidth + 10 : 0
            height: 17
            radius: 4
            color: Qt.rgba(badgeTone.r, badgeTone.g, badgeTone.b, 0.18)
            border.width: 1
            border.color: Qt.rgba(badgeTone.r, badgeTone.g, badgeTone.b, row.modelData.processAuto === false ? 1.0 : 0.6)
            opacity: row.dim ? 0.45 : 1.0
            readonly property color badgeTone: row.modelData.processColor ? row.modelData.processColor : Theme.cTextMuted
            Text {
                id: badgeText
                anchors.centerIn: parent
                text: row.modelData.process || ""
                color: Theme.darkMode ? Qt.lighter(badge.badgeTone, 1.35) : Qt.darker(badge.badgeTone, 1.25)
                font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true
            }
            HoverHandler { id: badgeHover }
            Tip {
                shown: badgeHover.hovered
                text: (row.modelData.processName || "") + (row.modelData.processAuto === false ? qsTr("（手动指定）") : "")
                      + "：" + (row.modelData.processWhy || "")
            }
        }

        Rectangle {                         // 设计检查报错的特征: 左边一道红条, 底色带一点红
            visible: row.feature && row.modelData.flagged === true
            x: 0; y: 3; width: parent.width; height: row.body - 6; radius: 6
            color: Qt.rgba(1, 0.2, 0.2, 0.10)
            border.width: 1; border.color: Qt.rgba(1, 0.25, 0.25, 0.55)
        }

        Column {
            id: column
            anchors.left: badge.right; anchors.leftMargin: 8
            anchors.right: parent.right; anchors.rightMargin: 6
            y: row.reference || row.root ? (row.body - 20) / 2 : 4
            spacing: 1
            visible: !row.bar
            Text {
                width: parent.width - (actions.active ? actions.width : 0)    // 名称给悬停按钮让位; 下面的说明文字用整行宽
                height: 20
                verticalAlignment: Text.AlignVCenter
                text: row.modelData.name + (row.modelData.editing && row.feature ? qsTr("　编辑中") : "")
                      + (row.folder ? "  <font color='" + Theme.cTextMuted + "'>" + row.modelData.count + "</font>" : "")
                textFormat: row.folder ? Text.StyledText : Text.PlainText
                elide: Text.ElideRight
                color: row.failed ? Theme.cError : row.folder ? row.tone : row.chosen ? Theme.cAccent : row.quiet ? Theme.cTextSec : Theme.cText
                opacity: row.dim ? 0.5 : 1.0
                font.family: Theme.font
                font.pixelSize: row.root ? Theme.textSize + 1 : Theme.textSize
                font.bold: row.root || row.folder
            }
            Text {
                width: parent.width
                visible: text !== ""
                text: row.modelData.note
                wrapMode: Text.Wrap
                color: row.failed ? Theme.cError : Theme.cTextMuted
                font.family: Theme.font; font.pixelSize: Theme.smallSize
            }
        }
        Loader {                        // 悬停时才造这两个按钮: 树一重建就是几十行, 每行先造好再藏起来白费时间
            id: actions
            anchors.right: parent.right; anchors.rightMargin: 4
            y: 1
            active: hover.hovered && row.feature && row.modelData.id !== "" && !app.sketchActive && !list.rolling
            sourceComponent: Row {
                spacing: 0
                IconBtn {
                    implicitWidth: 26; implicitHeight: 26; iconSize: 16
                    icon: row.modelData.suppressed ? "unsuppress" : "suppress"
                    tip: row.modelData.suppressed ? qsTr("解除压缩：重新启用这个特征") : qsTr("压缩：暂时当它不存在（参数保留）")
                    onClicked: app.toggleSuppress(row.modelData.id)
                }
                IconBtn { implicitWidth: 26; implicitHeight: 26; iconSize: 16; icon: "trash"; tip: qsTr("删除：删除这个特征"); action: "edit.delete"; onClicked: app.deleteFeature(row.modelData.id) }
            }
        }
    }
}
