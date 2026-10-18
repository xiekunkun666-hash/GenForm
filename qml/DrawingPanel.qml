// DrawingPanel.qml - 工程图的设置: 在窗口左边 (零件的设计树那个位置)。画哪个零件、图纸、比例、显示哪些视图、标题栏里填什么
import QtQuick
import QtQuick.Controls

Item {
    id: panel
    readonly property var state: drawing.state
    signal choosePart()

    component Head: Row {
        property string text: ""
        spacing: 6
        topPadding: 6
        Rectangle { width: 3; height: 12; radius: 1.5; color: Theme.cAccent; anchors.verticalCenter: headText.verticalCenter }
        Text { id: headText; text: parent.text; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
    }
    component Chip: Rectangle {
        id: chip
        property string text: ""
        property bool on: false
        signal clicked()
        width: Math.max(38, chipText.implicitWidth + 16); height: 26; radius: 5
        color: on ? Theme.cAccentStrong : (chipArea.containsMouse ? Theme.cBgHover : Theme.cBgInput)
        border.width: on ? 0 : 1; border.color: Theme.cDivider
        Text { id: chipText; anchors.centerIn: parent; text: chip.text; color: chip.on ? "#FFFFFF" : Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
        MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; onClicked: chip.clicked() }
    }
    component Check: Item {
        id: check
        property string text: ""
        property bool on: false
        signal clicked()
        width: parent ? parent.width : 100; height: 26
        Rectangle {
            width: 16; height: 16; radius: 4; anchors.verticalCenter: parent.verticalCenter
            color: check.on ? Theme.cAccentStrong : Theme.cBgInput
            border.width: check.on ? 0 : 1; border.color: Theme.cDivider
            Icon { anchors.centerIn: parent; size: 12; name: "check"; color: "#FFFFFF"; visible: check.on }
        }
        Text { x: 24; anchors.verticalCenter: parent.verticalCenter; text: check.text; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
        MouseArea { anchors.fill: parent; onClicked: check.clicked() }
    }

    Flickable {
        anchors.fill: parent; anchors.margins: 12
        contentHeight: column.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        Column {
            id: column
            width: parent.width
            spacing: 7

            Head { text: qsTr("零件") }
            Text {
                width: parent.width; elide: Text.ElideMiddle
                text: panel.state.source !== "" ? panel.state.source : qsTr("还没选")
                color: panel.state.source !== "" ? Theme.cText : Theme.cTextMuted
                font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true
            }
            Text { visible: panel.state.size !== ""; text: panel.state.size; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            Row {
                spacing: 6
                Chip { text: qsTr("选择零件…"); onClicked: panel.choosePart() }
                Chip { text: qsTr("重新投影"); visible: panel.state.ready; onClicked: drawing.project() }
            }
            Text { visible: panel.state.running; text: qsTr("正在投影…"); color: Theme.cAccent; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            Text { visible: panel.state.error !== ""; width: parent.width; wrapMode: Text.Wrap; text: panel.state.error; color: Theme.cBad; font.family: Theme.font; font.pixelSize: Theme.textSize }

            Head { text: qsTr("图纸") }
            Row {
                spacing: 4
                Repeater {
                    model: panel.state.sheets
                    delegate: Chip { required property string modelData; text: modelData; on: panel.state.sheet === modelData; onClicked: drawing.setSheet(modelData) }
                }
            }

            Head { text: qsTr("比例") + (panel.state.scale !== "" ? "　" + panel.state.scale : "") }
            Flow {
                width: parent.width; spacing: 4
                Repeater {
                    model: panel.state.scales
                    delegate: Chip { required property var modelData; text: modelData.title; on: panel.state.scaleChoice === modelData.id; onClicked: drawing.setScale(modelData.id) }
                }
            }

            Head { text: qsTr("视图") }
            Repeater {
                model: panel.state.views
                delegate: Check { required property var modelData; text: modelData.title; on: modelData.on; onClicked: drawing.toggleView(modelData.id) }
            }
            Chip { visible: panel.state.moved; text: qsTr("视图摆回原位"); onClicked: drawing.resetLayout() }

            Head { text: qsTr("显示") }
            Check { text: qsTr("隐藏线（虚线）"); on: panel.state.hidden; onClicked: drawing.toggle("hidden") }
            Check { text: qsTr("自动标长宽高"); on: panel.state.auto; onClicked: drawing.toggle("auto") }
            Check { text: qsTr("圆的中心线"); on: panel.state.centers; onClicked: drawing.toggle("centers") }

            Head { text: qsTr("标题栏") }
            Repeater {
                model: panel.state.title
                delegate: Item {
                    id: field
                    required property var modelData
                    width: column.width; height: 28
                    Text { anchors.verticalCenter: parent.verticalCenter; text: field.modelData.label; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.textSize }
                    TextField {
                        id: input
                        x: 44; width: parent.width - 44; height: 26
                        text: field.modelData.value
                        selectByMouse: true
                        color: Theme.cText
                        font.family: Theme.font; font.pixelSize: Theme.textSize
                        leftPadding: 6; rightPadding: 6; topPadding: 0; bottomPadding: 0
                        background: Rectangle { radius: 5; color: Theme.cBgInput; border.width: 1; border.color: input.activeFocus ? Theme.cAccent : Theme.cDivider }
                        onEditingFinished: drawing.setTitle(field.modelData.id, text)
                    }
                }
            }

            Item { width: 1; height: 4 }
            Repeater {
                model: panel.state.notes
                delegate: Text {
                    required property string modelData
                    width: column.width; wrapMode: Text.Wrap
                    text: modelData
                    color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11
                }
            }
        }
    }
}
