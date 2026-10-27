// StatusBar.qml - 状态栏: 光标下 / 选中的东西的说明; 右边是装配体的实时检查 (查到哪了 / 几处干涉 / 没有干涉)、
// 设计检查日志的按钮 (报错几条、警告几条, 点它拉出 / 收起日志), AI 接口开在哪 (apiText 是 Python 给的上下文属性)。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    Layout.fillWidth: true
    height: 26
    color: Theme.cBgTitle
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14; anchors.rightMargin: 14
        Text {
            text: app.hoverText !== "" ? app.hoverText : app.selectionText
            color: Theme.cTextSec
            font.family: Theme.font; font.pixelSize: Theme.smallSize
            Layout.fillWidth: true
            elide: Text.ElideRight
        }
        // ---- 实时检查 (装配体) ----
        Item {
            id: live
            visible: app.docKind === "assembly" && sim.live.on
            readonly property var state: sim.live
            readonly property bool bad: state.clashes > 0
            readonly property bool warn: !bad && state.gaps > 0
            implicitWidth: liveRow.implicitWidth + 16; implicitHeight: 22
            Rectangle { anchors.fill: parent; radius: 4; color: liveArea.containsMouse ? Theme.cBgHover : "transparent" }
            Row {
                id: liveRow
                anchors.centerIn: parent; spacing: 5
                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 13; height: 13; radius: 6.5
                    color: live.state.running ? "transparent" : live.bad ? Theme.cError : live.warn ? "#E98A3C" : Theme.cAxisY
                    border.width: live.state.running ? 1.5 : 0; border.color: Theme.cAccent
                    Icon { anchors.centerIn: parent; visible: !live.state.running; size: 9; color: "#FFFFFF"; name: live.bad ? "close" : "check" }
                    Rectangle { visible: live.state.running; width: 3; height: 3; radius: 1.5; color: Theme.cAccent; x: parent.width / 2 - 1.5; y: -1 }
                    RotationAnimation on rotation { running: live.state.running; loops: Animation.Infinite; from: 0; to: 360; duration: 900 }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: live.state.running ? (live.state.total > 0 ? qsTr("实时检查 %1 / %2").arg(live.state.done).arg(live.state.total) : qsTr("实时检查…"))
                        : live.state.error !== "" ? qsTr("实时检查没做完")
                        : live.bad ? qsTr("%1 处干涉").arg(live.state.clashes)
                        : live.warn ? qsTr("%1 处间隙太小").arg(live.state.gaps) : qsTr("没有干涉")
                    color: live.bad ? Theme.cError : Theme.cTextSec
                    font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: live.bad
                }
            }
            MouseArea { id: liveArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: app.runCheck() }
            Tip { shown: liveArea.containsMouse; text: live.state.error !== "" ? live.state.error : qsTr("实时检查：零件一变就在后台查件与件有没有压进去。点它跑一遍完整的设计检查（悬空、间隙、物料清单）") }
        }
        // ---- 设计检查的日志 ----
        Item {
            id: logButton
            visible: app.docKind !== "drawing"
            readonly property var counts: app.checkCounts
            readonly property int errors: counts.error || 0
            readonly property int warnings: counts.warning || 0
            implicitWidth: logRow.implicitWidth + 16; implicitHeight: 22
            Rectangle { anchors.fill: parent; radius: 4; color: app.checkOpen ? Theme.cAccentSoft : logArea.containsMouse ? Theme.cBgHover : "transparent" }
            Row {
                id: logRow
                anchors.centerIn: parent; spacing: 5
                Icon { anchors.verticalCenter: parent.verticalCenter; size: 14; name: "drc"; color: app.checkOpen ? Theme.cAccent : Theme.cTextSec }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: logButton.errors === 0 && logButton.warnings === 0
                    text: app.checkBusy ? qsTr("检查中…") : qsTr("日志")
                    color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize
                }
                Row {
                    visible: logButton.errors > 0
                    anchors.verticalCenter: parent.verticalCenter; spacing: 3
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: Theme.cError }
                    Text { text: logButton.errors; color: Theme.cError; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
                }
                Row {
                    visible: logButton.warnings > 0
                    anchors.verticalCenter: parent.verticalCenter; spacing: 3
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: Theme.darkMode ? "#E2B43C" : "#B7860B" }
                    Text { text: logButton.warnings; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                }
            }
            MouseArea { id: logArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: app.toggleCheckLog() }
            Tip { shown: logArea.containsMouse
                  text: app.checkOpen ? qsTr("收起设计检查的日志") : (logButton.errors + logButton.warnings > 0 || (logButton.counts.info || 0) > 0)
                        ? qsTr("拉出设计检查的日志：%1 条报错、%2 条警告").arg(logButton.errors).arg(logButton.warnings)
                        : qsTr("打开检查日志；需要检查时点击设计检查") }
        }
        Rectangle { width: 1; height: 14; color: Theme.cDivider; visible: logButton.visible }
        Rectangle { width: 6; height: 6; radius: 3; color: Theme.cAccent }
        Text {
            text: app.tr(apiText)
            color: Theme.cTextMuted
            font.family: Theme.font; font.pixelSize: Theme.smallSize
        }
    }
}
