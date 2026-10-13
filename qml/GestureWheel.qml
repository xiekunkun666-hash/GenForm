// GestureWheel.qml - 右键拖动出现的手势轮: 8 个命令围成一圈, 朝哪个方向划就执行哪个。
// 只负责画; 鼠标由三维视图识别 (viewport.gestureIndex 是现在指着的那一格)。
// items: [{icon, text}...], 从 "右" 开始逆时针。
import QtQuick

Item {
    id: wheel
    property var items: []
    property int current: -1
    readonly property real ring: 70             // 图标中心离轮心的距离; 和视图里 "划到多远就执行" 的距离对应

    width: 260
    height: 260

    Rectangle {                                 // 底盘
        anchors.centerIn: parent
        width: wheel.ring * 2 + 58; height: width; radius: width / 2
        color: Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.78)
        border.width: 1; border.color: Theme.cDivider
    }
    Rectangle {                                 // 轮心: 回到这里松手 = 取消
        anchors.centerIn: parent
        width: 36; height: 36; radius: 18
        color: "transparent"
        border.width: 1; border.color: Theme.cDivider
    }

    Repeater {
        model: wheel.items
        delegate: Item {
            id: cell
            required property var modelData
            required property int index
            readonly property real angle: index * Math.PI / 4
            readonly property bool on: index === wheel.current
            x: wheel.width / 2 + Math.cos(angle) * wheel.ring - width / 2
            y: wheel.height / 2 - Math.sin(angle) * wheel.ring - height / 2
            width: 48; height: 48

            Rectangle {
                anchors.fill: parent
                radius: 24
                color: cell.on ? Theme.cAccent : Theme.cBgCard
                border.width: 1
                border.color: cell.on ? Theme.cAccent : Theme.cDivider
                scale: cell.on ? 1.12 : 1.0
                Behavior on scale { NumberAnimation { duration: 70 } }
            }
            Icon {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 6
                size: 20
                name: cell.modelData.icon
                color: cell.on ? "#FFFFFF" : Theme.cText
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                y: 27
                width: 58
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: cell.modelData.text
                color: cell.on ? "#FFFFFF" : Theme.cTextSec
                font.family: Theme.font; font.pixelSize: 10
            }
        }
    }
}
