// ProgressCard.qml - 重算的进度条: 打开大零件、改前面的特征、加载装配体的零件时浮在视图下方。算得快 (不到半秒) 就不出来, 免得一闪一闪。
import QtQuick

Rectangle {
    id: card
    readonly property var state: app.progress
    property bool shown: false
    visible: opacity > 0
    opacity: shown ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    width: 380; height: 64; radius: 10
    color: Qt.rgba(Theme.cBgCard.r, Theme.cBgCard.g, Theme.cBgCard.b, 0.97)
    border.width: 1; border.color: Theme.cDivider

    readonly property bool working: app.busy || state.loading      // 装配体加载零件时 app.busy 不亮 (那是查询, 不是重算)
    Timer { id: wait; interval: 450; onTriggered: card.shown = card.working }
    onWorkingChanged: {
        if (!working) { wait.stop(); shown = false }
        else if (!shown && !wait.running) wait.start()
    }
    Connections {
        target: app
        function onChanged() {
            if (!card.working) { wait.stop(); card.shown = false }
            else if (!card.shown && !wait.running) wait.start()
        }
    }

    Text {
        x: 16; y: 12
        width: parent.width - 32 - count.width - 8
        elide: Text.ElideRight
        text: card.state.what === "pairs" ? qsTr("正在检查件与件之间的关系")
            : card.state.what === "motion" ? qsTr("正在查运动干涉") + "　" + card.state.name
            : card.state.loading ? qsTr("正在加载零件") + "　" + card.state.name
            : card.state.total > 0 ? qsTr("正在计算") + "　" + card.state.name : qsTr("正在计算…")
        color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize
    }
    Text {
        id: count
        anchors.right: parent.right; anchors.rightMargin: 16; y: 12
        text: card.state.total > 0 ? (card.state.done + 1) + " / " + card.state.total : ""
        color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.textSize
    }
    Rectangle {
        x: 16; y: 40; width: parent.width - 32; height: 6; radius: 3
        color: Theme.cBgInput
        Rectangle {
            height: parent.height; radius: 3
            width: Math.max(parent.height, parent.width * card.state.fraction)
            color: Theme.cAccentStrong
            Behavior on width { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        }
    }
}
