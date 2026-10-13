// IconBtn.qml - 只有图标的小按钮 (标题栏、视图角上用)
import QtQuick
import QtQuick.Controls

Rectangle {
    id: button
    property string icon: ""
    property string tip: ""
    property string action: ""              // 这个按钮对应动作表里的哪个动作: 悬停说明里显示它的快捷键
    property bool active: false
    property bool danger: false             // 关闭按钮: 悬停变红
    property real iconSize: 18
    property color tint: Theme.cTextSec     // 图标平时的颜色
    signal clicked()

    implicitWidth: 34
    implicitHeight: 30
    radius: 6
    opacity: enabled ? 1.0 : 0.32
    color: danger && area.containsMouse ? "#E5484D"
         : active ? Theme.cAccentSoft
         : area.pressed ? Theme.cDivider : (area.containsMouse ? Theme.cBgHover : "transparent")
    Behavior on color { ColorAnimation { duration: 90 } }

    Icon {
        anchors.centerIn: parent
        name: button.icon
        size: button.iconSize
        color: button.danger && area.containsMouse ? "#FFFFFF" : (button.active || area.containsMouse ? Theme.cAccent : button.tint)
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        onClicked: button.clicked()
    }
    Tip { shown: area.containsMouse && !area.pressed; text: button.tip; keys: button.action !== "" ? (app.keyMap[button.action] || "") : "" }
}
