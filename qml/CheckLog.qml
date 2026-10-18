// CheckLog.qml - 设计检查 (评估 → 设计检查) 的日志窗口: 从视图底部滑上来。
// 一行一条: 级别色块 (红 报错 / 黄 警告 / 灰 提示)、标题、说明、提到的特征; 点一行 = 在设计树里选中它提到的特征。
// 报错里提到的件在视图里标红 (右上角可以关掉标红); 检查以后模型又改了, 顶上提示 "结果可能过期, 重新检查"。
import QtQuick
import QtQuick.Controls

Rectangle {
    id: log
    property real openHeight: Math.min(300, parent ? parent.height * 0.42 : 300)
    readonly property bool shown: app.checkOpen
    readonly property var counts: app.checkCounts
    readonly property color cWarn: Theme.darkMode ? "#E2B43C" : "#B7860B"
    property string filter: ""            // "" 全部 / error / warning / info

    height: openHeight
    y: shown ? parent.height - height : parent.height + 8
    property bool allowed: true           // 主窗口: 只在零件文档里
    visible: allowed && y < parent.height - 1
    Behavior on y { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
    color: Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.97)
    border.width: 1; border.color: Theme.cDivider
    radius: 10

    function tone(level) { return level === "error" ? Theme.cError : level === "warning" ? cWarn : Theme.cTextMuted }

    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = false }   // 不让点击穿到视图上

    // ---- 顶上一条: 标题、计数 (点了只看那一级)、标红开关、重新检查、关闭 ----
    Row {
        id: head
        x: 14; y: 8
        height: 30
        spacing: 10
        Icon { anchors.verticalCenter: parent.verticalCenter; name: "drc"; size: 18; color: (counts.error || 0) > 0 ? Theme.cError : Theme.cAccent }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: app.checkBusy ? qsTr("设计检查：正在查…") : qsTr("设计检查")
            color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true
        }
        Repeater {
            model: [{ level: "error", text: qsTr("报错") }, { level: "warning", text: qsTr("警告") }, { level: "info", text: qsTr("提示") }]
            delegate: Rectangle {
                required property var modelData
                readonly property bool on: log.filter === modelData.level
                anchors.verticalCenter: parent.verticalCenter
                width: chip.implicitWidth + 18; height: 24; radius: 12
                color: on ? Qt.rgba(log.tone(modelData.level).r, log.tone(modelData.level).g, log.tone(modelData.level).b, 0.22)
                          : chipArea.containsMouse ? Theme.cBgHover : "transparent"
                border.width: 1; border.color: log.tone(modelData.level)
                Text {
                    id: chip
                    anchors.centerIn: parent
                    text: modelData.text + " " + (log.counts[modelData.level] || 0)
                    color: log.tone(modelData.level); font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true
                }
                MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: log.filter = parent.on ? "" : modelData.level }
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: app.checkStale
            text: qsTr("模型改过了，结果可能过期")
            color: log.cWarn; font.family: Theme.font; font.pixelSize: Theme.smallSize
        }
    }
    Row {
        anchors.right: parent.right; anchors.rightMargin: 8; y: 8
        spacing: 2
        IconBtn { icon: app.checkHighlight ? "eye" : "eye_off"; tip: app.checkHighlight ? qsTr("标红：报错的件在视图里标红；点一下关掉") : qsTr("标红：点一下在视图里把报错的件标红"); onClicked: app.toggleCheckHighlight() }
        IconBtn { icon: "reset"; tip: qsTr("重新检查"); enabled: !app.checkBusy; onClicked: app.runCheck() }
        IconBtn { icon: "close"; tip: qsTr("关闭：收起日志，视图恢复原来的颜色"); onClicked: app.closeCheck() }
    }
    Rectangle { x: 0; y: 44; width: parent.width; height: 1; color: Theme.cDivider }

    // ---- 一条条结果 ----
    ListView {
        id: list
        x: 6; y: 50
        width: parent.width - 12; height: parent.height - 56
        clip: true
        spacing: 2
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        model: app.checkIssues.map((item, index) => Object.assign({ index: index }, item)).filter((item) => log.filter === "" || item.level === log.filter)
        delegate: Rectangle {
            required property var modelData
            width: list.width - 10
            height: Math.max(34, text.implicitHeight + 14)
            radius: 6
            color: issueArea.containsMouse ? Theme.cBgHover : "transparent"
            Rectangle { x: 6; y: 9; width: 4; height: parent.height - 18; radius: 2; color: log.tone(modelData.level) }
            Column {
                id: text
                x: 20; y: 7
                width: parent.width - 30
                spacing: 2
                Text {
                    width: parent.width
                    text: modelData.title
                    wrapMode: Text.Wrap
                    color: modelData.level === "error" ? Theme.cError : Theme.cText
                    font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: modelData.level === "error"
                }
                Text {
                    width: parent.width
                    visible: modelData.detail !== ""
                    text: modelData.detail
                    wrapMode: Text.Wrap
                    color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize
                }
                Text {
                    width: parent.width
                    visible: modelData.names.length > 0 && modelData.names.length <= 6 && modelData.title.indexOf(modelData.names[0]) < 0
                    text: qsTr("涉及：") + modelData.names.join("、")
                    elide: Text.ElideRight
                    color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize
                }
            }
            MouseArea {
                id: issueArea
                anchors.fill: parent; hoverEnabled: true
                cursorShape: modelData.features.length > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: app.focusIssue(modelData.index)
            }
        }
        Text {
            anchors.centerIn: parent
            visible: list.count === 0 && !app.checkBusy
            text: log.filter === "" ? qsTr("没有发现问题") : qsTr("这一级没有")
            color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.textSize
        }
    }
}
