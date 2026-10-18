// MeasurePanel.qml - 测量结果: 浮在视图左上角。上面一句现在该干什么, 下面一行一个数 (最要紧的几个加粗、蓝色)。
import QtQuick

Rectangle {
    id: panel
    readonly property var state: app.measure
    visible: app.measuring
    width: 280
    height: column.implicitHeight + 24
    radius: 10
    color: Qt.rgba(Theme.cBgCard.r, Theme.cBgCard.g, Theme.cBgCard.b, 0.96)
    border.width: 1; border.color: Theme.cDivider
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = true }

    Column {
        id: column
        x: 14; y: 12
        width: parent.width - 28
        spacing: 6
        Item {
            width: parent.width; height: 26
            Icon { anchors.verticalCenter: parent.verticalCenter; size: 19; name: "measure"; color: Theme.cAccent }
            Text { x: 28; anchors.verticalCenter: parent.verticalCenter; text: qsTr("测量"); color: Theme.cText; font.family: Theme.font; font.pixelSize: 14; font.bold: true }
            IconBtn { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; implicitWidth: 26; implicitHeight: 26; iconSize: 15; icon: "cancel"; tip: qsTr("结束测量"); onClicked: app.toggleMeasure() }
        }
        Text {
            width: parent.width
            text: panel.state.hint
            wrapMode: Text.Wrap
            color: Theme.cTextSec
            font.family: Theme.font; font.pixelSize: Theme.smallSize
        }
        Rectangle { width: parent.width; height: 1; color: Theme.cDivider; visible: panel.state.rows.length > 0 }
        Repeater {
            model: panel.state.rows
            delegate: Item {
                required property var modelData
                width: column.width; height: 22
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.label
                    color: modelData.strong ? Theme.cText : Theme.cTextSec
                    font.family: Theme.font; font.pixelSize: Theme.textSize
                }
                TextInput {             // 能选中复制
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    text: modelData.value
                    readOnly: true; selectByMouse: true
                    color: modelData.strong ? Theme.cAccent : Theme.cText
                    selectionColor: Theme.cAccentStrong
                    font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: modelData.strong
                }
            }
        }
    }
}
