// SketchProps.qml - 草图里选中图形时的属性栏 (左栏的 PropertyManager 页): 现有几何关系、添加几何关系、选项、参数、额外参数。
// docked: 放在左栏里, 铺满那一页, 没选中东西时显示一句提示。
// 内容由控制器给 (app.sketchProps); 按钮都交给 app.sketchAction, 数字交给 app.setField。
// 标题右边的 ✓ (app.sketchAction("ok")): 画图工具 = 结束回到选择, 选中图形 = 放下回设计树。
// 拿着画图工具时是工具页 (info.tool: 只有说明), 点了几何关系小图标时是关系页 (info.actions: 删除)。
import QtQuick
import QtQuick.Controls

Rectangle {
    id: panel
    readonly property var info: app.sketchProps
    readonly property bool shown: app.sketchActive && info !== null && info !== undefined
    readonly property bool toolPage: shown && !!info.tool
    readonly property bool heldShown: shown && !toolPage && !(info.held.length === 0 && info.actions.length > 0)   // 尺寸页不列关系
    property bool docked: false
    visible: docked || shown
    width: 264
    height: docked ? (parent ? parent.height : 600) : Math.min(column.implicitHeight + 24, parent ? parent.height - y - 12 : 600)
    radius: 10
    color: docked ? "transparent" : Qt.rgba(Theme.cBgCard.r, Theme.cBgCard.g, Theme.cBgCard.b, 0.97)
    border.width: docked ? 0 : 1; border.color: Theme.cDivider
    clip: true
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = true }

    component Section: Text {
        color: Theme.cTextMuted
        font.family: Theme.font; font.pixelSize: 11; font.bold: true
        topPadding: 4
    }
    component Row2: Item {                  // 一行参数: 名称 + 数 (能改的是输入框, 只读的是字)
        id: row
        property var field
        width: column.width; height: 28
        Text { anchors.verticalCenter: parent.verticalCenter; width: 92; elide: Text.ElideRight; text: row.field ? row.field.label : ""; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.textSize }
        TextField {
            id: input
            visible: row.field && row.field.type === "number" && !row.field.readonly
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 100; height: 26
            readonly property string shownValue: row.field && row.field.type === "number" ? String(Math.round(row.field.value * 10000) / 10000) : ""
            text: shownValue
            selectByMouse: true
            color: Theme.cText
            font.family: Theme.font; font.pixelSize: Theme.textSize
            horizontalAlignment: TextInput.AlignRight
            leftPadding: 4; rightPadding: 10 + unit.implicitWidth; topPadding: 0; bottomPadding: 0
            background: Rectangle { radius: 5; color: Theme.cBgInput; border.width: 1; border.color: input.activeFocus ? Theme.cAccent : Theme.cDivider }
            onActiveFocusChanged: if (activeFocus) selectAll()
            onEditingFinished: {
                const value = Number(text.replace(",", "."))
                if (text.trim() !== "" && isFinite(value) && text !== shownValue) app.setField(row.field.key, value)
            }
            Keys.onEscapePressed: { text = shownValue; app.escape() }
            Text { id: unit; anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter; text: row.field && row.field.unit ? row.field.unit : ""; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize }
        }
        Text {
            visible: row.field && row.field.type === "number" && row.field.readonly === true
            anchors.right: parent.right; anchors.rightMargin: 6; anchors.verticalCenter: parent.verticalCenter
            text: row.field && row.field.type === "number" ? (Math.round(row.field.value * 10000) / 10000) + " " + (row.field.unit || "") : ""
            color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize
        }
        TextField {
            id: words
            visible: row.field && row.field.type === "text"
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 100; height: 26
            text: row.field && row.field.type === "text" ? row.field.value : ""
            selectByMouse: true
            color: Theme.cText
            font.family: Theme.font; font.pixelSize: Theme.textSize
            leftPadding: 6; topPadding: 0; bottomPadding: 0
            background: Rectangle { radius: 5; color: Theme.cBgInput; border.width: 1; border.color: words.activeFocus ? Theme.cAccent : Theme.cDivider }
            onTextEdited: app.setField(row.field.key, text)
        }
        Check {
            visible: row.field && row.field.type === "bool"
            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            on: row.field && row.field.type === "bool" ? row.field.value : false
            onToggled: app.setField(row.field.key, !on)
        }
    }
    component Check: Rectangle {
        id: check
        property bool on: false
        signal toggled()
        width: 18; height: 18; radius: 4
        color: on ? Theme.cAccentStrong : Theme.cBgInput
        border.width: on ? 0 : 1; border.color: Theme.cDivider
        Icon { anchors.centerIn: parent; size: 14; name: "check"; color: "#FFFFFF"; visible: check.on }
        MouseArea { anchors.fill: parent; anchors.margins: -5; cursorShape: Qt.PointingHandCursor; onClicked: check.toggled() }
    }

    Text {                                  // 左栏里没选中东西: 说一句这里会显示什么
        visible: panel.docked && !panel.shown
        x: 12; y: 16; width: parent.width - 24
        wrapMode: Text.Wrap
        lineHeight: 1.35
        text: app.sketchActive ? qsTr("在草图里点选线条、圆弧或点，这里显示它的属性和几何关系。点空白处回到设计树。")
                               : qsTr("编辑草图时，点选线条、圆弧或点，这里显示它的属性和几何关系。")
        color: Theme.cTextMuted
        font.family: Theme.font; font.pixelSize: Theme.smallSize
    }

    Flickable {
        visible: panel.shown
        anchors.fill: parent; anchors.margins: panel.docked ? 4 : 12
        contentHeight: column.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        Column {
            id: column
            width: parent.width
            spacing: 6

            Item {                          // 标题 + ✓
                width: parent.width; height: 32
                Text {
                    anchors.left: parent.left; anchors.right: okButton.left; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                    elide: Text.ElideRight
                    text: panel.shown ? panel.info.title : ""; color: Theme.cText; font.family: Theme.font; font.pixelSize: 14; font.bold: true
                }
                Rectangle {
                    id: okButton
                    objectName: "propsOk"
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    width: 30; height: 30; radius: 15
                    color: okArea.pressed ? Theme.cAccentStrong : okArea.containsMouse ? Theme.cAccentSoft : "transparent"
                    border.width: 1.5; border.color: Theme.cAccent
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Icon { anchors.centerIn: parent; size: 17; name: "check"; color: okArea.pressed ? "#FFFFFF" : Theme.cAccent }
                    MouseArea { id: okArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: app.sketchAction("ok") }
                    Tip { text: panel.toolPage ? qsTr("确定：结束这个工具，回到选择") : qsTr("确定：放下选中的，回到设计树"); shown: okArea.containsMouse }
                }
            }
            Text {                          // 工具怎么用 / 这个关系是怎么来的
                visible: panel.shown && panel.info.note !== ""
                width: parent.width; wrapMode: Text.Wrap; lineHeight: 1.3
                text: panel.shown ? panel.info.note : ""
                color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize
            }

            Section { text: qsTr("现有几何关系"); visible: panel.heldShown }
            Flow {
                visible: panel.heldShown
                width: parent.width; spacing: 4
                Repeater {
                    model: panel.shown ? panel.info.held : []
                    delegate: Rectangle {
                        required property string modelData
                        width: heldText.implicitWidth + 16; height: 22; radius: 11
                        color: Theme.cAccentSoft; border.width: 1; border.color: Theme.cAccentLine
                        Text { id: heldText; anchors.centerIn: parent; text: modelData; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                    }
                }
                Text { visible: panel.shown && panel.info.held.length === 0; text: qsTr("没有"); color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            }

            Repeater {                      // 关系页: 删除这个关系
                model: panel.shown ? panel.info.actions : []
                delegate: Rectangle {
                    required property var modelData
                    width: column.width; height: 30; radius: 6
                    color: actionArea.containsMouse ? Theme.cAccentSoft : Theme.cBgInput
                    border.width: 1; border.color: Theme.cDivider
                    Row {
                        anchors.centerIn: parent; spacing: 6
                        Icon { anchors.verticalCenter: parent.verticalCenter; size: 15; name: "trash"; color: Theme.cIcon }
                        Text { anchors.verticalCenter: parent.verticalCenter; text: modelData.title; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
                    }
                    MouseArea { id: actionArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: app.sketchAction(modelData.id) }
                }
            }

            Section { text: qsTr("添加几何关系"); visible: panel.shown && panel.info.relations.length > 0 }
            Flow {
                width: parent.width; spacing: 2
                Repeater {
                    model: panel.shown ? panel.info.relations : []
                    delegate: IconBtn {
                        required property var modelData
                        implicitWidth: 32; implicitHeight: 30
                        icon: modelData.icon; iconSize: 18; tint: Theme.cIcon
                        tip: modelData.title
                        onClicked: app.sketchAction(modelData.id)
                    }
                }
            }
            Text {
                visible: panel.shown && panel.info.relations.length > 0
                width: parent.width; wrapMode: Text.Wrap
                text: qsTr("关系是照着摆一次，不是保持住的约束：之后再拖动不会自动保持。“现有”是按现在的形状量出来的")
                color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11
            }

            Section { text: qsTr("选项"); visible: panel.shown && panel.info.options.length > 0 }
            Repeater {
                model: panel.shown ? panel.info.options : []
                delegate: Item {
                    required property var modelData
                    width: column.width; height: 26
                    Check { id: box; anchors.verticalCenter: parent.verticalCenter; on: modelData.value; onToggled: app.sketchAction(modelData.id) }
                    Text { x: 26; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
                }
            }

            Section { text: qsTr("参数"); visible: panel.shown && panel.info.params.length > 0 }
            Repeater {
                model: panel.shown ? panel.info.params.length : 0
                delegate: Row2 { required property int index; field: panel.shown ? panel.info.params[index] : null }
            }

            Section { text: qsTr("额外参数"); visible: panel.shown && panel.info.extra.length > 0 }
            Repeater {
                model: panel.shown ? panel.info.extra.length : 0
                delegate: Row2 { required property int index; field: panel.shown ? panel.info.extra[index] : null }
            }
        }
    }
}
