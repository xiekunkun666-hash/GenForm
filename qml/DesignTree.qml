// DesignTree.qml - 设计树: 零件 → 基准面 / 原点 → 特征 (草图收在用它的拉伸下面) → 回退线。
// 单击选中, 双击基准面 = 在它上面画草图, 双击特征 = 编辑它; 悬停特征出现 抑制 / 删除。
// 出错的特征标红并写明原因; 正在编辑的草图标蓝。
// 回退线: 蓝色的横条, 上下拖到两个特征之间 — 它下面的特征暂不计算 (变淡); 双击它 = 回到最后。
// 点基准面: 旁边浮出一排小按钮 (草图绘制 / 显示隐藏 / 放大所选范围 / 正视于)。点 "材质": 选材质。
// 点特征或草图: 浮出它的小工具条 (编辑特征 / 编辑草图 / 压缩 / 退回 / 隐藏显示 / 放大所选范围 / 正视于 / 外观…)。
import QtQuick
import QtQuick.Controls

ListView {
    id: list
    clip: true
    spacing: 1
    model: app.tree
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

    readonly property var marks: ({ "sketch": "草", "extrude": "拉", "fillet": "圆", "chamfer": "倒" })
    property bool rolling: false        // 正在拖回退线
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
        const picking = app.hint !== "" && !app.sketchActive      // 正等着选基准面画草图: 点了就直接进草图
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
        const items = app.featureContext(identifier)
        if (items.length === 0) return
        featureBar.target = identifier
        featureBar.items = items
        featureBar.x = 30
        featureBar.y = below
        featureBar.open()
    }

    ContextBar { id: featureBar }

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
        property string plane: ""
        property bool shown: false
        padding: 4
        background: Rectangle { color: Theme.cBgCard; radius: 9; border.width: 1; border.color: Theme.cDivider }
        contentItem: Row {
            spacing: 2
            IconBtn { icon: "sketch"; iconSize: 19; tip: "草图绘制：在这个基准面上画草图"; onClicked: { planeBar.close(); app.planeAction(planeBar.plane, "sketch") } }
            IconBtn { icon: planeBar.shown ? "eye_off" : "eye"; iconSize: 19; tip: planeBar.shown ? "隐藏这个基准面" : "显示这个基准面"; onClicked: { planeBar.shown = !planeBar.shown; app.planeAction(planeBar.plane, "toggle") } }
            IconBtn { icon: "zoom_sel"; iconSize: 19; tip: "放大所选范围：把这个基准面放满画面"; onClicked: app.planeAction(planeBar.plane, "zoom") }
            IconBtn { icon: "normal"; iconSize: 19; tip: "正视于：把视角转到正对这个基准面"; onClicked: app.planeAction(planeBar.plane, "normal") }
        }
    }

    Rectangle {                         // 拖的时候: 松手会落在这里
        z: 20
        visible: list.rolling && list.dropCount >= 0
        x: 6; y: list.dropY - 1
        width: list.width - 12; height: 2; radius: 1
        color: Theme.cAccent
    }

    delegate: Rectangle {
        id: row
        required property var modelData
        readonly property bool bar: modelData.kind === "rollback"
        readonly property bool feature: modelData.kind === "feature"
        readonly property bool failed: modelData.state === "error"
        readonly property bool dim: modelData.suppressed || modelData.rolled || modelData.state === "skipped"
        readonly property real indent: 6 + modelData.depth * 16
        width: list.width
        height: bar ? 14 : Math.max(28, column.implicitHeight + 8)
        radius: 6
        color: bar ? "transparent"
             : failed ? Theme.cErrorSoft
             : (modelData.selected || modelData.editing) ? Theme.cAccentSoft
             : hover.hovered && modelData.kind !== "root" && modelData.kind !== "origin" ? Theme.cBgHover : "transparent"
        border.width: modelData.selected && !bar ? 1 : 0
        border.color: Theme.cAccentLine

        HoverHandler { id: hover }
        TapHandler {
            enabled: !row.bar
            onTapped: (point) => {
                if (row.modelData.kind === "plane") list.planeTapped(row.modelData.id, row.modelData.shown, row.y - list.contentY + row.height + 2)
                else if (row.modelData.kind === "material") list.popAt(materialMenu, row)
                else if (row.feature && row.modelData.id !== "") {
                    if (actions.visible && point.position.x >= actions.x) return        // 点的是右边的 抑制 / 删除
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
                Tip { shown: barArea.containsMouse && !barArea.pressed; text: "回退线：捏住上下拖到两个特征之间，它下面的特征暂不计算；双击回到最后" }
            }
        }

        // 展开 / 收起 (下面收着草图的拉伸才有)
        Text {
            x: row.indent - 2; y: 5
            width: 14; height: 18
            visible: row.modelData.expandable && !row.bar
            text: row.modelData.expanded ? "▾" : "▸"
            color: Theme.cTextMuted
            font.pixelSize: 12
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
            TapHandler { onTapped: app.toggleExpand(row.modelData.id) }
        }

        // 节点图标
        Item {
            id: glyph
            x: row.indent + 14; y: 4
            width: 20; height: 20
            visible: !row.bar
            opacity: row.dim ? 0.35 : (row.modelData.hidden === true ? 0.5 : 1.0)      // 隐藏着的淡一点
            Rectangle {                     // 特征: 一个带字的小块 (中性底, 蓝字; 出错的是红的)
                anchors.fill: parent
                visible: row.feature
                radius: 5
                color: row.failed ? Theme.cErrorSoft : (row.modelData.selected || row.modelData.editing ? Theme.cAccent : Theme.cAccentSoft)
                border.width: 1
                border.color: row.failed ? Theme.cError : (row.modelData.selected || row.modelData.editing ? Theme.cAccent : Theme.cAccentLine)
                Text {
                    anchors.centerIn: parent
                    text: row.modelData.mark || list.marks[row.modelData.type] || "?"
                    color: row.failed ? Theme.cError : (row.modelData.selected || row.modelData.editing ? "#FFFFFF" : Theme.cAccent)
                    font.family: Theme.font; font.pixelSize: 11; font.bold: true
                }
            }
            Icon {
                anchors.centerIn: parent
                visible: !row.feature
                size: 17
                name: row.modelData.kind === "plane" ? "plane" : row.modelData.kind === "origin" ? "origin"
                    : row.modelData.kind === "material" ? "material" : "part"
                color: row.modelData.kind === "root" ? Theme.cText : (row.modelData.selected || row.modelData.editing ? Theme.cAccent : Theme.cIcon)
                opacity: row.modelData.kind === "plane" && !row.modelData.shown && !row.modelData.selected ? 0.5 : 1.0    // 没显示着的基准面淡一点
            }
        }

        Column {
            id: column
            anchors.left: glyph.right; anchors.leftMargin: 8
            anchors.right: parent.right; anchors.rightMargin: 6
            y: 4
            spacing: 1
            visible: !row.bar
            Text {
                width: parent.width - (actions.visible ? actions.width : 0)   // 名称给悬停按钮让位; 下面的说明文字用整行宽
                height: 20
                verticalAlignment: Text.AlignVCenter
                text: row.modelData.name + (row.modelData.editing && row.feature ? "　编辑中" : "")
                elide: Text.ElideRight
                color: row.failed ? Theme.cError : (row.modelData.editing ? Theme.cAccent : Theme.cText)
                opacity: row.dim ? 0.5 : 1.0
                font.family: Theme.font
                font.pixelSize: Theme.textSize
                font.bold: row.modelData.kind === "root"
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
        Row {
            id: actions
            anchors.right: parent.right; anchors.rightMargin: 4
            y: 1
            spacing: 0
            visible: hover.hovered && row.feature && row.modelData.id !== "" && !app.sketchActive && !list.rolling
            ToolBtn {
                compact: true
                text: row.modelData.suppressed ? "恢复" : "抑制"
                tip: row.modelData.suppressed ? "重新启用这个特征" : "暂时当它不存在（参数保留）"
                onClicked: app.toggleSuppress(row.modelData.id)
            }
            ToolBtn { compact: true; text: "删除"; tip: "删除这个特征 (Delete)"; onClicked: app.deleteFeature(row.modelData.id) }
        }
    }
}
