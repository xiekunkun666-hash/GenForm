// RibbonBtn.qml - 工具栏上的大按钮: 上面图标, 下面文字。active = 当前正在用的工具
import QtQuick
import QtQuick.Controls

Rectangle {
    id: button
    property string icon: ""
    property string text: ""
    property string tip: ""
    property string action: ""              // 这个按钮对应动作表里的哪个动作: 悬停说明里显示它的快捷键
    property bool active: false
    property color tint: Theme.cIcon        // 图标颜色 (完成=绿, 放弃=红 这类要强调的按钮用)
    signal clicked()

    implicitWidth: Math.max(54, label.implicitWidth + 18)
    implicitHeight: 54
    radius: 8
    opacity: enabled ? 1.0 : 0.35
    color: active ? Theme.cAccentSoft
                  : area.pressed ? Theme.cDivider : (area.containsMouse ? Theme.cBgHover : "transparent")
    border.width: active ? 1 : 0
    border.color: Theme.cAccentLine
    Behavior on color { ColorAnimation { duration: 90 } }

    Icon {
        name: button.icon
        color: button.active || area.containsMouse ? Theme.cAccent : button.tint     // 悬停时图标亮一档
        Behavior on color { ColorAnimation { duration: 110 } }
        anchors.horizontalCenter: parent.horizontalCenter
        y: 7
    }
    Text {
        id: label
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom; anchors.bottomMargin: 6
        text: button.text
        color: button.active || area.containsMouse ? Theme.cText : Theme.cTextSec
        font.family: Theme.font; font.pixelSize: Theme.smallSize
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: button.clicked()
    }
    Tip { shown: area.containsMouse && !area.pressed; text: button.tip; keys: button.action !== "" ? (app.keyMap[button.action] || "") : "" }
}
