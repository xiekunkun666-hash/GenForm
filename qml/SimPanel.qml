// SimPanel.qml - 仿真面板: 浮在视图左上角。静力分析 / 风阻估算 / 装配检查 三种, 开着哪种显示哪种。
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs

Rectangle {
    id: panel
    readonly property var state: sim.state
    readonly property string mode: state.mode
    // docked: 开着的文档就是一个装配体时, 这个面板不浮在视图上, 而是占着窗口左边那一栏 (设计树的位置), 也关不掉
    property bool docked: false
    visible: docked ? state.pinned === true : (mode !== "" && state.pinned !== true)
    width: docked ? (parent ? parent.width - 1 : 400) : (mode === "assembly" ? 400 : 320)
    height: docked ? (parent ? parent.height : 600) : Math.min(column.implicitHeight + 24, parent ? parent.height - 24 : 600)
    radius: docked ? 0 : 10
    color: docked ? Theme.cBg : Qt.rgba(Theme.cBgCard.r, Theme.cBgCard.g, Theme.cBgCard.b, 0.97)
    border.width: docked ? 0 : 1; border.color: Theme.cDivider
    clip: true
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = true }

    FileDialog {
        id: partDialog
        title: qsTr("插入零件")
        nameFilters: [qsTr("零件 (*.gform *.step *.stp)")]
        onAccepted: sim.addPart(selectedFile)
    }

    FileDialog {
        id: asmSave
        title: qsTr("保存装配体")
        fileMode: FileDialog.SaveFile
        defaultSuffix: "gasm"
        nameFilters: [qsTr("GenForm 装配体 (*.gasm)")]
        onAccepted: sim.saveAssembly(selectedFile)
    }
    FileDialog {
        id: asmOpen
        title: qsTr("打开装配体")
        nameFilters: [qsTr("GenForm 装配体 (*.gasm)")]
        onAccepted: sim.openAssembly(selectedFile)
    }

    component Label: Text { color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.textSize; anchors.verticalCenter: parent ? parent.verticalCenter : undefined }
    component Num: TextField {              // 填一个数; 回车或离开时交上去
        id: num
        property string value: ""
        property string unit: ""
        signal commit(string text)
        width: 64; height: 26
        text: value
        selectByMouse: true
        color: Theme.cText
        font.family: Theme.font; font.pixelSize: Theme.textSize
        horizontalAlignment: TextInput.AlignRight
        leftPadding: 4; rightPadding: unit === "" ? 6 : 8 + unitText.implicitWidth
        topPadding: 0; bottomPadding: 0
        background: Rectangle { radius: 5; color: Theme.cBgInput; border.width: 1; border.color: num.activeFocus ? Theme.cAccent : Theme.cDivider }
        onActiveFocusChanged: if (activeFocus) selectAll()
        onEditingFinished: if (text !== value) commit(text)
        Keys.onEscapePressed: { text = value; focus = false }
        Text { id: unitText; anchors.right: parent.right; anchors.rightMargin: 5; anchors.verticalCenter: parent.verticalCenter; text: num.unit; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize }
    }
    component Btn: Rectangle {              // 面板里的按钮: 图标 + 字
        id: btn
        property string icon: ""
        property string text: ""
        property bool primary: false
        property bool busy: false
        property string tip: ""
        signal clicked()
        width: btnRow.implicitWidth + 22; height: 30; radius: 6
        opacity: busy ? 0.55 : 1
        color: primary ? (btnArea.containsMouse ? Theme.cAccent : Theme.cAccentStrong) : (btnArea.containsMouse ? Theme.cBgHover : Theme.cBgInput)
        border.width: primary ? 0 : 1; border.color: Theme.cDivider
        Row {
            id: btnRow
            anchors.centerIn: parent; spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; size: 16; name: btn.icon; visible: btn.icon !== ""; color: btn.primary ? "#FFFFFF" : Theme.cText }
            Text { anchors.verticalCenter: parent.verticalCenter; text: btn.text; color: btn.primary ? "#FFFFFF" : Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
        }
        MouseArea { id: btnArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: if (!btn.busy) btn.clicked() }
        Tip { shown: btnArea.containsMouse; text: btn.tip }
    }
    component Choice: Row {                 // 几个里选一个
        id: choice
        property var options: []
        property string chosen: ""
        signal picked(string id)
        spacing: 4
        Repeater {
            model: choice.options
            delegate: Rectangle {
                required property var modelData
                readonly property bool on: choice.chosen === modelData.id
                width: Math.max(34, optionText.implicitWidth + 18); height: 26; radius: 5
                color: on ? Theme.cAccentStrong : (optionArea.containsMouse ? Theme.cBgHover : Theme.cBgInput)
                border.width: on ? 0 : 1; border.color: Theme.cDivider
                Text { id: optionText; anchors.centerIn: parent; text: modelData.title; color: parent.on ? "#FFFFFF" : Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
                MouseArea { id: optionArea; anchors.fill: parent; hoverEnabled: true; onClicked: choice.picked(modelData.id) }
            }
        }
    }

    Flickable {
        anchors.fill: parent; anchors.margins: 12; anchors.leftMargin: 14; anchors.rightMargin: 14
        contentHeight: column.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        Column {
            id: column
            width: parent.width
            spacing: 8

            Item {
                width: parent.width; height: 26
                Icon { anchors.verticalCenter: parent.verticalCenter; size: 19; color: Theme.cAccent; name: panel.mode === "static" ? "stress" : (panel.mode === "drag" ? "wind" : "assembly") }
                Text {
                    x: 28; anchors.verticalCenter: parent.verticalCenter
                    text: panel.mode === "static" ? qsTr("静力分析") : (panel.mode === "drag" ? qsTr("风阻估算") : (panel.docked ? qsTr("装配体里的零件") : qsTr("装配检查")))
                    color: Theme.cText; font.family: Theme.font; font.pixelSize: 14; font.bold: true
                }
                IconBtn { visible: !panel.docked; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; implicitWidth: 26; implicitHeight: 26; iconSize: 15; icon: "cancel"; tip: qsTr("关闭"); onClicked: sim.close() }
            }

            // ---- 静力分析 ----
            Column {
                visible: panel.mode === "static"
                width: parent.width; spacing: 8
                Text { width: parent.width; wrapMode: Text.Wrap; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize
                       text: qsTr("在视图里点选面（Ctrl 多选），再点下面的按钮把它们记成固定面或受力面") }
                Repeater {
                    model: [{ role: "fixed", title: qsTr("固定面"), count: panel.state.fixed }, { role: "loaded", title: qsTr("受力面"), count: panel.state.loaded }]
                    delegate: Item {
                        required property var modelData
                        width: column.width; height: 30
                        Label { text: modelData.title }
                        Text { x: 62; anchors.verticalCenter: parent.verticalCenter; text: modelData.count > 0 ? modelData.count + qsTr(" 个面") : qsTr("还没选"); color: modelData.count > 0 ? Theme.cAccent : Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.textSize }
                        Row {
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                            IconBtn { implicitWidth: 28; implicitHeight: 28; iconSize: 16; icon: "eye"; visible: modelData.count > 0; tip: qsTr("在视图里亮出来看"); onClicked: sim.showFaces(modelData.role) }
                            Btn { text: qsTr("用选中的面"); onClicked: sim.takeFaces(modelData.role) }
                        }
                    }
                }
                Item {
                    width: parent.width; height: 28
                    Label { text: qsTr("力") }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                        Repeater {
                            model: 3
                            delegate: Row {
                                required property int index
                                spacing: 3
                                Text { anchors.verticalCenter: parent.verticalCenter; text: "XYZ"[index]; color: [Theme.cAxisX, Theme.cAxisY, Theme.cAxisZ][index]; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
                                Num { value: panel.state.force[index]; unit: "N"; width: 70; onCommit: (text) => sim.setForce(index, text) }
                            }
                        }
                    }
                }
                Item {
                    width: parent.width; height: 28
                    Label { text: qsTr("网格") }
                    Choice { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; options: panel.state.qualities; chosen: panel.state.quality; onPicked: (id) => sim.setQuality(id) }
                }
                Btn { width: parent.width; primary: true; icon: "play"; busy: panel.state.running; text: panel.state.running ? qsTr("正在算…") : qsTr("开始分析"); onClicked: sim.runStatic() }
            }

            // ---- 风阻估算 ----
            Column {
                visible: panel.mode === "drag"
                width: parent.width; spacing: 8
                Item {
                    width: parent.width; height: 28
                    Label { text: qsTr("气流方向") }
                    Choice { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; options: [{ id: "X", title: "X" }, { id: "Y", title: "Y" }, { id: "Z", title: "Z" }]; chosen: panel.state.axis; onPicked: (id) => sim.setDrag("axis", id) }
                }
                Repeater {
                    model: [{ key: "speed", title: qsTr("速度"), unit: "m/s" }, { key: "cd", title: qsTr("阻力系数"), unit: "" }, { key: "density", title: qsTr("空气密度"), unit: "kg/m³" }]
                    delegate: Item {
                        required property var modelData
                        width: column.width; height: 28
                        Label { text: modelData.title }
                        Num { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 110; value: panel.state[modelData.key]; unit: modelData.unit; onCommit: (text) => sim.setDrag(modelData.key, text) }
                    }
                }
                Btn { width: parent.width; primary: true; icon: "play"; busy: panel.state.running; text: panel.state.running ? qsTr("正在算…") : qsTr("估算"); onClicked: sim.runDrag() }
            }

            // ---- 装配检查 ----
            Column {
                visible: panel.mode === "assembly"
                width: parent.width; spacing: 6
                Repeater {
                    model: panel.state.parts
                    delegate: Rectangle {
                        id: partRow
                        required property var modelData
                        required property int index
                        width: column.width
                        height: partColumn.implicitHeight + 14
                        radius: 7
                        color: Theme.cBgInput
                        border.width: 1; border.color: modelData.state === "bad" ? Theme.cBad : Theme.cDivider
                        Column {
                            id: partColumn
                            x: 9; y: 7; width: parent.width - 18; spacing: 5
                            Item {
                                width: parent.width; height: 24
                                Rectangle { width: 20; height: 20; radius: 10; anchors.verticalCenter: parent.verticalCenter; color: Theme.cAccentStrong
                                            Text { anchors.centerIn: parent; text: partRow.index + 1; color: "#FFFFFF"; font.family: Theme.font; font.pixelSize: 11; font.bold: true } }
                                Rectangle { x: 27; width: 10; height: 10; radius: 2; anchors.verticalCenter: parent.verticalCenter; visible: modelData.tint !== ""; color: modelData.tint === "" ? "transparent" : modelData.tint }
                                Text { x: modelData.tint !== "" ? 43 : 28; width: parent.width - x - 118; anchors.verticalCenter: parent.verticalCenter; elide: Text.ElideMiddle; text: modelData.name; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
                                Row {
                                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 1
                                    IconBtn { implicitWidth: 26; implicitHeight: 24; iconSize: 14; icon: "mirror"; visible: modelData.file; active: modelData.mirror; tip: modelData.mirror ? qsTr("镜像着（左右相反的那一个件）：再点一下不镜像") : qsTr("镜像：对零件自己的 XZ 面翻过来，左边的件变成右边的"); onClicked: sim.mirrorPart(partRow.index) }
                                    IconBtn { implicitWidth: 26; implicitHeight: 24; iconSize: 14; icon: "up"; tip: qsTr("早一步装"); onClicked: sim.shiftPart(partRow.index, -1) }
                                    IconBtn { implicitWidth: 26; implicitHeight: 24; iconSize: 14; icon: "down"; tip: qsTr("晚一步装"); onClicked: sim.shiftPart(partRow.index, 1) }
                                    IconBtn { implicitWidth: 26; implicitHeight: 24; iconSize: 14; icon: "trash"; danger: true; visible: modelData.file; tip: qsTr("从装配体里拿掉"); onClicked: sim.removePart(partRow.index) }
                                }
                            }
                            Repeater {
                                model: modelData.file ? [{ field: "move", title: qsTr("位置"), unit: "" }, { field: "turn", title: qsTr("转角"), unit: "°" }] : []
                                delegate: Item {
                                    id: placeRow
                                    required property var modelData
                                    width: partColumn.width; height: 26
                                    Text { anchors.verticalCenter: parent.verticalCenter; text: placeRow.modelData.title; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                                    Row {
                                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                                        Repeater {
                                            model: 3
                                            delegate: Row {
                                                required property int index
                                                spacing: 3
                                                Text { anchors.verticalCenter: parent.verticalCenter; text: "XYZ"[index]; color: [Theme.cAxisX, Theme.cAxisY, Theme.cAxisZ][index]; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
                                                Num { width: 82; height: 24; value: partRow.modelData[placeRow.modelData.field][index]; unit: placeRow.modelData.unit; onCommit: (text) => sim.placePart(partRow.index, placeRow.modelData.field, index, text) }
                                            }
                                        }
                                    }
                                }
                            }
                            Row {
                                visible: modelData.status !== ""
                                width: parent.width; spacing: 5
                                Icon { size: 15; name: modelData.state === "bad" ? "cancel" : "check"; color: modelData.state === "bad" ? Theme.cBad : Theme.cGood }
                                Text { width: parent.width - 20; wrapMode: Text.Wrap; text: modelData.status; color: modelData.state === "bad" ? Theme.cBad : Theme.cText; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                            }
                        }
                    }
                }
                Text {
                    visible: panel.state.parts.length === 0
                    width: parent.width; wrapMode: Text.Wrap
                    text: qsTr("还没有零件：点下面的“插入零件…”，选 .gform 或 .step 文件")
                    color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.textSize
                }
                Row {
                    width: parent.width; spacing: 6
                    Btn { width: panel.docked ? (parent.width - 6) / 2 : (parent.width - 86) / 2; icon: "plus"; text: qsTr("插入零件…"); onClicked: partDialog.open() }
                    Btn {
                        id: stdButton
                        width: panel.docked ? (parent.width - 6) / 2 : (parent.width - 86) / 2; icon: "screw"; text: qsTr("标准件…")
                        tip: qsTr("插入标准件：轴承、滚针、销、螺丝、螺母、垫圈、铜柱、挡圈、钢球，按国标尺寸生成，放在装配体旁边的 standard/ 文件夹")
                        onClicked: stdPicker.start(Qt.point(0, height + 4))
                        StdPicker { id: stdPicker }
                    }
                    Btn { visible: !panel.docked; width: 34; icon: "open"; tip: qsTr("打开装配体 (.gasm)"); onClicked: asmOpen.open() }
                    Btn { visible: !panel.docked; width: 34; icon: "save"; tip: qsTr("保存装配体 (.gasm)：记下零件文件、位置和装配顺序"); onClicked: asmSave.open() }
                }
                Row {
                    width: parent.width; spacing: 6
                    Btn { width: (parent.width - 6) / 2; primary: true; icon: "clash"; busy: panel.state.running; text: qsTr("干涉检查"); onClicked: sim.runInterference() }
                    Btn { width: (parent.width - 6) / 2; primary: true; icon: "order"; busy: panel.state.running; text: qsTr("装配顺序检查"); onClicked: sim.runSequence() }
                }
                Row {
                    width: parent.width; spacing: 6
                    Btn { width: (parent.width - 12) / 3; icon: "thread"; busy: panel.state.running; text: qsTr("螺纹检查"); onClicked: sim.runFasteners() }
                    Btn { width: (parent.width - 12) / 3; icon: "check"; text: qsTr("对齐螺纹"); onClicked: sim.alignThreads() }
                    Btn { width: (parent.width - 12) / 3; icon: "dimension"; busy: panel.state.running; text: qsTr("尺寸链"); onClicked: sim.runStack("Z") }
                }
                Text { visible: panel.state.running; text: qsTr("正在算…"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            }

            // ---- 出错 / 结果 / 说明 ----
            Text { visible: panel.state.error !== ""; width: parent.width; wrapMode: Text.Wrap; text: panel.state.error; color: Theme.cBad; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
            Rectangle { width: parent.width; height: 1; color: Theme.cDivider; visible: panel.state.rows.length > 0 }
            Repeater {
                model: panel.state.rows
                delegate: Item {
                    required property var modelData
                    width: column.width; height: 22
                    Text { anchors.verticalCenter: parent.verticalCenter; width: parent.width - valueText.width - 8; elide: Text.ElideRight; text: modelData.label; color: modelData.strong ? Theme.cText : Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.textSize }
                    TextInput {
                        id: valueText
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        text: modelData.value; readOnly: true; selectByMouse: true
                        color: modelData.bad ? Theme.cBad : (modelData.strong ? Theme.cAccent : Theme.cText)
                        selectionColor: Theme.cAccentStrong
                        font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: modelData.strong
                    }
                }
            }
            Item {                          // 云图的色标
                visible: panel.state.legend !== ""
                width: parent.width; height: 30
                Rectangle {
                    width: parent.width; height: 10; radius: 3
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Qt.rgba(0.13, 0.30, 0.85, 1) }
                        GradientStop { position: 0.25; color: Qt.rgba(0.10, 0.75, 0.90, 1) }
                        GradientStop { position: 0.5; color: Qt.rgba(0.20, 0.80, 0.30, 1) }
                        GradientStop { position: 0.75; color: Qt.rgba(0.95, 0.85, 0.15, 1) }
                        GradientStop { position: 1.0; color: Qt.rgba(0.90, 0.15, 0.12, 1) }
                    }
                }
                Text { y: 14; text: "0"; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11 }
                Text { y: 14; anchors.right: parent.right; text: panel.state.legend; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11 }
            }
            Repeater {
                model: panel.state.notes
                delegate: Text {
                    required property string modelData
                    width: column.width; wrapMode: Text.Wrap
                    text: modelData
                    color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11
                }
            }
        }
    }
}
