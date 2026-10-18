// AssemblyTree.qml - 装配体的设计树 (和 SOLIDWORKS 的 FeatureManager 一样): 装配体 → 前视 / 上视 / 右视基准面、原点 →
// 布局草图 (装配体里画的, 跟着 .gasm 存) → 零部件。点基准面弹出 草图绘制 / 正视于 / 放大; 点草图弹出它的小工具条。
// 零部件一行: 零件图标 (镜像的是镜像图标) · (固定) 第一个 · 名字<第几个> · 标准 / 外购 / 非标 小标签; 隐藏的变淡, 设计检查报错的标红。
// 单击选中并弹出小工具条 (视图里它变蓝; 视图里点它, 树也跳到这一行), 双击打开零件, 右键菜单 (打开零件、编辑位置、镜像、隐藏、孤立、挪顺序、删除)。
import QtQuick
import QtQuick.Controls

ListView {
    id: list
    signal editPart(int index)          // 右键 "编辑位置" / 双击行右边的位置: 左栏翻到属性管理器
    clip: true
    spacing: 2
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    readonly property var parts: sim.components
    // 前面固定的几行 (装配体、三个基准面、原点), 后面是零部件
    readonly property var heads: [{ kind: "root", label: sim.assemblyName, icon: "assembly" },
                                  { kind: "plane", plane: "XZ", label: qsTr("前视基准面"), icon: "plane" },
                                  { kind: "plane", plane: "XY", label: qsTr("上视基准面"), icon: "plane" },
                                  { kind: "plane", plane: "YZ", label: qsTr("右视基准面"), icon: "plane" },
                                  { kind: "origin", label: qsTr("原点"), icon: "origin" }]
                                  .concat(app.layoutSketches.map((sketch) => ({ kind: "sketch", id: sketch.id, label: sketch.name,
                                                                               icon: "sketch", selected: sketch.selected })))
                                  .concat(sim.joints.length > 0 ? [{ kind: "group", label: qsTr("运动副"), icon: "hinge" }] : [])
                                  .concat(sim.joints.map((joint) => ({ kind: "joint", index: joint.index, icon: joint.kind === "slide" ? "move" : "hinge",
                                                                      label: joint.name, selected: joint.selected,
                                                                      value: joint.value.toFixed(joint.kind === "slide" ? 0 : 0) + joint.unit })))
    model: heads.length + parts.length

    property int shown: -1              // 上一次滚到眼前的选中零部件: 视图里点了别的才滚过去
    Connections {
        target: sim
        function onChanged() {
            if (sim.picked !== list.shown) {
                list.shown = sim.picked
                if (sim.picked >= 0) Qt.callLater(() => list.positionViewAtIndex(list.heads.length + sim.picked, ListView.Contain))
            }
        }
        function onEditRequested(index) { list.editPart(index) }
    }

    // 单击一个零部件: 选中它, 在它下面弹出小工具条 (打开零件、编辑位置、镜像、隐藏、孤立、放大所选范围)
    function partTapped(index, below) {
        sim.selectPart(index)
        const items = sim.partContext(index)
        if (items.length === 0) return
        partBar.target = "part:" + index
        partBar.items = items
        partBar.x = 30
        partBar.y = below
        partBar.open()
    }
    ContextBar { id: partBar }

    // 点了基准面: 弹出 草图绘制 / 正视于 / 放大所选范围 (正等着选基准面画草图时, 点了就直接进草图)
    function planeTapped(plane, below) {
        partBar.close()
        const picking = app.hint !== "" && !app.sketchActive
        sim.selectPart(-1)
        app.selectPlane(plane)
        if (picking || app.sketchActive) return
        planeBar.plane = plane
        planeBar.x = 30
        planeBar.y = below
        planeBar.open()
    }
    Popup {
        id: planeBar
        property string plane: ""
        padding: 4
        background: Rectangle { color: Theme.cBgCard; radius: 9; border.width: 1; border.color: Theme.cDivider }
        contentItem: Row {
            spacing: 2
            IconBtn { icon: "sketch"; iconSize: 19; tip: qsTr("草图绘制：在这个基准面上画布局草图（跟着装配体存）"); onClicked: { planeBar.close(); app.planeAction(planeBar.plane, "sketch") } }
            IconBtn { icon: "zoom_sel"; iconSize: 19; tip: qsTr("放大所选范围：把这个基准面放满画面"); onClicked: app.planeAction(planeBar.plane, "zoom") }
            IconBtn { icon: "normal"; iconSize: 19; tip: qsTr("正视于：把视角转到正对这个基准面"); onClicked: app.planeAction(planeBar.plane, "normal") }
        }
    }
    // 点了布局草图: 选中它, 弹出它的小工具条 (编辑草图、编辑草图平面、隐藏…, 和零件的设计树一样)
    function sketchTapped(identifier, below) {
        planeBar.close()
        sim.selectPart(-1)
        app.selectFeature(identifier)
        const items = app.featureContext(identifier)
        if (items.length === 0) return
        partBar.target = identifier
        partBar.items = items
        partBar.x = 30
        partBar.y = below
        partBar.open()
    }

    function menuAt(index, x, below) {
        partBar.close()
        const items = sim.partMenu(index)
        if (items.length === 0) return
        partMenu.target = index
        partMenu.items = items
        partMenu.x = Math.max(8, Math.min(list.width - 200, x))
        partMenu.y = below
        partMenu.open()
    }
    MenuList {
        id: partMenu
        property int target: -1
        itemWidth: 196
        onPicked: (id) => sim.partAction(target, id)
    }

    delegate: Rectangle {
        id: row
        required property int index
        readonly property bool head: index < list.heads.length
        readonly property var info: head ? list.heads[index] : list.parts[index - list.heads.length]
        readonly property int part: head ? -1 : index - list.heads.length
        readonly property bool chosen: (!head || info.kind === "sketch" || info.kind === "joint") && info.selected === true
        readonly property real gap: head && index === list.heads.length - 1 ? 11 : 0   // 固定的几行 (到布局草图) 下面一道分隔线
        readonly property real body: head && info.kind === "root" ? 32 : head ? 26 : 28
        width: list.width
        height: body + gap
        color: "transparent"

        Rectangle {
            width: parent.width; height: row.body
            radius: 6
            color: !row.head && row.info.bad ? Theme.cErrorSoft : row.chosen ? Theme.cAccentSoft : hover.hovered ? Theme.cBgHover : "transparent"
            border.width: !row.head && row.info.bad ? 1 : 0; border.color: Theme.cError
            Rectangle { visible: row.chosen; x: 0; y: 5; width: 3; height: parent.height - 10; radius: 1.5; color: Theme.cAccent }
        }
        Rectangle { visible: row.gap > 0; x: 12; y: row.body + row.gap / 2; width: parent.width - 24; height: 1; color: Theme.cDivider }

        Row {
            x: row.head && row.info.kind === "root" ? 8 : row.head && row.info.kind === "joint" ? 44 : 26
            height: row.body
            spacing: 6
            opacity: !row.head && row.info.hidden ? 0.4 : 1.0
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                size: 17
                name: row.head ? row.info.icon : (row.info.mirror ? "mirror" : "part")
                color: row.head ? (row.info.kind === "root" ? Theme.cAccent : Theme.cTextMuted) : (row.chosen ? Theme.cAccent : Theme.cTextSec)
            }
            Text {
                visible: !row.head && row.info.fixed
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("(固定)")
                color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: Math.min(implicitWidth, row.width - 120)
                elide: Text.ElideRight
                text: row.info.label
                color: row.head && row.info.kind !== "root" ? Theme.cTextSec : Theme.cText
                font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: row.head && row.info.kind === "root"
            }
        }
        Text {                          // 运动副现在开到多少
            visible: row.head && row.info.kind === "joint"
            anchors.right: parent.right; anchors.rightMargin: 12
            y: (row.body - height) / 2
            text: row.head && row.info.kind === "joint" ? row.info.value : ""
            color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize
        }
        Rectangle {                     // 实时检查: 和别的件压进去了
            visible: !row.head && row.info.clash.length > 0
            anchors.right: kindMark.visible ? kindMark.left : parent.right; anchors.rightMargin: 6
            y: (row.body - height) / 2
            width: 18; height: 18; radius: 9
            color: Theme.cError
            Icon { anchors.centerIn: parent; name: "close"; size: 11; color: "#FFFFFF" }
        }
        Rectangle {                     // 标准 / 外购 / 非标
            id: kindMark
            visible: !row.head && row.info.kind !== ""
            anchors.right: parent.right; anchors.rightMargin: 10
            y: (row.body - height) / 2
            width: kindText.implicitWidth + 10; height: 18; radius: 4
            color: "transparent"
            border.width: 1; border.color: !row.head && row.info.kindColor !== "" ? row.info.kindColor : Theme.cDivider
            Text {
                id: kindText
                anchors.centerIn: parent
                text: row.head ? "" : row.info.kind
                color: !row.head && row.info.kindColor !== "" ? row.info.kindColor : Theme.cTextMuted
                font.family: Theme.font; font.pixelSize: 11
            }
        }

        HoverHandler { id: hover }
        TapHandler {
            acceptedButtons: Qt.RightButton
            onTapped: (point) => {
                if (row.head && row.info.kind !== "root") return
                if (!row.head) sim.selectPart(row.part)
                list.menuAt(row.part, point.position.x, row.y - list.contentY + row.body + 2)
            }
        }
        TapHandler {
            onTapped: {
                const below = row.y - list.contentY + row.body + 2
                if (!row.head) list.partTapped(row.part, below)
                else if (row.info.kind === "plane") list.planeTapped(row.info.plane, below)
                else if (row.info.kind === "sketch") list.sketchTapped(row.info.id, below)
                else if (row.info.kind === "joint") { partBar.close(); planeBar.close(); sim.selectJoint(row.info.index); list.editPart(-1) }
                else { partBar.close(); planeBar.close(); sim.selectPart(-1) }
            }
            onDoubleTapped: {
                if (!row.head) { partBar.close(); sim.openPart(row.part) }
                else if (row.info.kind === "sketch") { partBar.close(); app.contextAction(row.info.id, "edit_sketch") }
            }
        }
        Tip {
            shown: hover.hovered && !row.head
            text: row.head ? "" : (row.info.file + (row.info.spec !== "" ? "\n" + row.info.spec : "")
                                   + (row.info.process !== "" ? "\n" + qsTr("工艺：") + row.info.process : "")
                                   + (row.info.unit > 0 ? "\n" + qsTr("每件约 ¥") + Math.round(row.info.unit).toLocaleString(Qt.locale(), 'f', 0) : "")
                                   + (row.info.mirror ? "\n" + qsTr("镜像摆放：左右相反的那一个件") : "")
                                   + (row.info.clash.length > 0 ? "\n" + qsTr("干涉：和 ") + row.info.clash.join("、") + qsTr(" 压进去了") : ""))
        }
    }
}
