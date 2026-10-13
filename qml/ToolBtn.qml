// ToolBtn.qml - 工具栏 / 面板上的文字按钮。tip 是悬停说明 (带快捷键)
import QtQuick
import QtQuick.Controls

Rectangle {
    id: button
    property string text: ""
    property string tip: ""
    property string action: ""              // 这个按钮对应动作表里的哪个动作: 悬停说明里显示它的快捷键
    property bool primary: false
    property bool compact: false
    signal clicked()

    implicitWidth: label.implicitWidth + (compact ? 16 : 24)
    implicitHeight: compact ? 26 : 32
    radius: 6
    opacity: enabled ? 1.0 : 0.38
    color: primary ? (area.pressed ? Qt.darker(Theme.cAccentStrong, 1.15) : (area.containsMouse ? Theme.cAccent : Theme.cAccentStrong))
                   : (area.pressed ? Theme.cDivider : (area.containsMouse ? Theme.cBgHover : "transparent"))
    Behavior on color { ColorAnimation { duration: 90 } }

    Text {
        id: label
        anchors.centerIn: parent
        text: button.text
        color: button.primary ? "#FFFFFF" : Theme.cText
        font.family: Theme.font
        font.pixelSize: button.compact ? Theme.smallSize : Theme.textSize
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
