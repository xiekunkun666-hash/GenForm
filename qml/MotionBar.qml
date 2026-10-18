// MotionBar.qml - 装配体的动画 (和 SOLIDWORKS 的运动算例一样): 浮在视图底下的一条时间轴。
// 播放 = 所有运动副 (车门、车盖) 一起 打开 → 停一下 → 关上; 时间轴可以拖着看任一时刻; 放完 / 暂停以后实时检查按那个位置查干涉。
import QtQuick

Rectangle {
    id: bar
    property bool shown: false
    readonly property var motion: sim.motion
    visible: shown && motion.count > 0
    width: Math.min(560, parent ? parent.width - 40 : 560)
    height: 48
    radius: 12
    color: Qt.rgba(Theme.cBgCard.r, Theme.cBgCard.g, Theme.cBgCard.b, 0.96)
    border.width: 1; border.color: Theme.cDivider
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = true }

    Row {
        anchors.fill: parent; anchors.leftMargin: 10; anchors.rightMargin: 8
        spacing: 10
        Rectangle {                         // 播放 / 暂停
            anchors.verticalCenter: parent.verticalCenter
            width: 32; height: 32; radius: 16
            color: playArea.containsMouse ? Theme.cAccent : Theme.cAccentStrong
            Icon { anchors.centerIn: parent; size: 16; color: "#FFFFFF"; name: bar.motion.playing ? "pause" : "play" }
            MouseArea { id: playArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: sim.playMotion() }
            Tip { shown: playArea.containsMouse; text: bar.motion.playing ? qsTr("暂停") : qsTr("播放：%1 个运动副一起打开、停一下、再关上").arg(bar.motion.count) }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: 76
            text: bar.motion.time.toFixed(1) + " / " + bar.motion.length.toFixed(1) + " s"
            color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize
        }
        ValueSlider {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 32 - 76 - 28 - 30
            from: 0; to: bar.motion.length; value: bar.motion.time
            onMoved: (value) => sim.scrubMotion(value)
            onReleased: sim.settleJoint()
        }
        IconBtn {
            anchors.verticalCenter: parent.verticalCenter
            implicitWidth: 26; implicitHeight: 26; iconSize: 14; icon: "close"; tip: qsTr("收起动画")
            onClicked: { if (bar.motion.playing) sim.playMotion(); bar.shown = false }
        }
    }
}
