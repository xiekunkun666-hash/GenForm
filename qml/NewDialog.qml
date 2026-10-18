// NewDialog.qml - 新建: 选要建哪一种文档 — 零件 / 装配体 / 工程图
import QtQuick
import QtQuick.Controls

Popup {
    id: dialog
    modal: true
    anchors.centerIn: Overlay.overlay
    padding: 22
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { color: Theme.cBgCard; radius: 12; border.width: 1; border.color: Theme.cDivider }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 140 } }

    contentItem: Column {
        spacing: 16
        Text { text: qsTr("新建"); color: Theme.cText; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
        Row {
            spacing: 14
            Repeater {
                model: [{ id: "part", icon: "cube", title: qsTr("零件"), text: qsTr("一个实体：画草图，再拉伸、切除、倒角…") },
                        { id: "assembly", icon: "assembly", title: qsTr("装配体"), text: qsTr("把几个零件摆到一起，查干涉、查装配顺序") },
                        { id: "drawing", icon: "drawing", title: qsTr("工程图"), text: qsTr("零件的三视图排在图纸上，标尺寸，导出 PDF / DXF") }]
                delegate: Rectangle {
                    id: card
                    required property var modelData
                    width: 178; height: 190; radius: 10
                    color: cardArea.containsMouse ? Theme.cAccentSoft : Theme.cBgInput
                    border.width: cardArea.containsMouse ? 1.5 : 1
                    border.color: cardArea.containsMouse ? Theme.cAccent : Theme.cDivider
                    scale: cardArea.pressed ? 0.97 : 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Behavior on scale { NumberAnimation { duration: 90 } }
                    Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 26; size: 56; name: card.modelData.icon; color: cardArea.containsMouse ? Theme.cAccent : Theme.cIcon }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter; y: 98
                        text: card.modelData.title
                        color: Theme.cText; font.family: Theme.font; font.pixelSize: 15; font.bold: true
                    }
                    Text {
                        x: 14; y: 126; width: parent.width - 28
                        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                        text: card.modelData.text
                        color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize; lineHeight: 1.25
                    }
                    MouseArea {
                        id: cardArea
                        anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                        onClicked: { dialog.close(); app.newOf(card.modelData.id) }
                    }
                }
            }
        }
        Text {
            width: 178 * 3 + 28; wrapMode: Text.Wrap
            text: qsTr("装配体和工程图是在现在打开的零件上做的：零件里有实体，它就是装配体的第一个零件、工程图画的那个零件；也可以进去以后再选别的零件文件")
            color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11
        }
    }
}
