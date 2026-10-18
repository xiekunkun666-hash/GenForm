// ValueSlider.qml - 一条横的滑块: 运动副开到多少度、动画放到第几秒。拖着时一直发 moved(值), 松手发 released()。
import QtQuick

Item {
    id: slider
    property real from: 0
    property real to: 1
    property real value: 0
    readonly property bool pressed: area.pressed
    signal moved(real value)
    signal released()
    implicitHeight: 22
    readonly property real share: to > from ? Math.min(Math.max((value - from) / (to - from), 0), 1) : 0

    Rectangle {                         // 轨道
        id: track
        anchors.verticalCenter: parent.verticalCenter
        x: 7; width: parent.width - 14; height: 4; radius: 2
        color: Theme.cBgInput
        border.width: 1; border.color: Theme.cDivider
        Rectangle { width: parent.width * slider.share; height: parent.height; radius: 2; color: Theme.cAccentStrong }
    }
    Rectangle {                         // 把手
        width: 14; height: 14; radius: 7
        anchors.verticalCenter: parent.verticalCenter
        x: track.x + track.width * slider.share - width / 2
        color: area.pressed ? Theme.cAccent : "#FFFFFF"
        border.width: 2; border.color: Theme.cAccentStrong
        scale: area.pressed || area.containsMouse ? 1.15 : 1.0
        Behavior on scale { NumberAnimation { duration: 100 } }
    }
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        preventStealing: true
        function at(x) { return slider.from + (slider.to - slider.from) * Math.min(Math.max((x - track.x) / Math.max(track.width, 1), 0), 1) }
        onPressed: (mouse) => slider.moved(at(mouse.x))
        onPositionChanged: (mouse) => { if (pressed) slider.moved(at(mouse.x)) }
        onReleased: slider.released()
    }
}
