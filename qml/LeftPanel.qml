// LeftPanel.qml - 左栏: 设计树 / 属性管理器 (PropertyManager) 两页 — 零件和装配体都是 (装配体的设计树列零部件, 和 SOLIDWORKS 一样);
// 工程图时是图纸设置。
// 草图里选中了图形 (或拿着画图工具、点了关系图标 / 尺寸) 就切到属性页, 什么都没选回设计树。要选零件时发 choosePart。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: leftPanel
    signal choosePart()
    Layout.preferredWidth: app.docKind === "assembly" ? 300 : (app.docKind === "drawing" ? 292 : 264)
    Layout.fillHeight: true
    color: Theme.cBg
    // 现在是哪一页: "tree" 设计树 (默认) / "props" PropertyManager。
    // 草图里选中了图形 (换选另一个也算) 就切到属性页; 点空白处 (什么都没选) 回到设计树
    property string page: "tree"
    readonly property string propsKey: app.sketchActive && app.sketchProps ? app.sketchProps.key : ""
    onPropsKeyChanged: page = propsKey !== "" ? "props" : "tree"
    readonly property bool assembly: app.docKind === "assembly"
    onAssemblyChanged: page = "tree"
    // 工程图: 这一栏是图纸的设置
    DrawingPanel { anchors.fill: parent; anchors.rightMargin: 1; visible: app.docKind === "drawing"; onChoosePart: leftPanel.choosePart() }
    ColumnLayout {
        visible: app.docKind === "part" || leftPanel.assembly
        anchors.fill: parent
        anchors.margins: 10
        anchors.topMargin: 12
        spacing: 8

        Rectangle {                 // 页签: 设计树 / PropertyManager
            objectName: "leftTabs"
            Layout.fillWidth: true
            implicitHeight: 32
            radius: 8
            color: Theme.cBgWorkspace
            Row {
                anchors.fill: parent; anchors.margins: 3
                spacing: 3
                Repeater {
                    model: [{ id: "tree", icon: "tree", title: qsTr("设计树"),
                              tip: leftPanel.assembly ? qsTr("设计树：装配体、基准面和零部件") : qsTr("设计树：零件、基准面和特征") },
                            { id: "props", icon: "props", title: qsTr("属性管理器"),
                              tip: leftPanel.assembly ? qsTr("属性管理器：选中的零部件的文件、类别、位置和镜像；没选时是装配体的检查结果")
                                                      : qsTr("属性管理器：草图里选中的线条、圆弧、点的属性") }]
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool current: leftPanel.page === modelData.id
                        objectName: "leftTab_" + modelData.id
                        width: (parent.width - 3) * (modelData.id === "tree" ? 0.45 : 0.55); height: parent.height     // 第二页的名字长一些 (英文是 PropertyManager)
                        radius: 6
                        color: current ? Theme.cBg : (leftTabArea.containsMouse ? Theme.cBgHover : "transparent")
                        border.width: current ? 1 : 0; border.color: Theme.cDivider
                        Row {
                            anchors.centerIn: parent
                            spacing: 6
                            Icon { anchors.verticalCenter: parent.verticalCenter; name: modelData.icon; size: 16; color: current ? Theme.cAccent : Theme.cTextMuted }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.title
                                color: current ? Theme.cText : Theme.cTextSec
                                font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: current
                            }
                        }
                        MouseArea { id: leftTabArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: leftPanel.page = modelData.id }
                        Tip { shown: leftTabArea.containsMouse; text: modelData.tip }
                    }
                }
            }
        }
        DesignTree { visible: !leftPanel.assembly && leftPanel.page === "tree"; Layout.fillWidth: true; Layout.fillHeight: true }
        SketchProps {               // 盖住设计树的那一页
            docked: true
            visible: (!leftPanel.assembly || app.sketchActive) && leftPanel.page === "props"
            Layout.fillWidth: true; Layout.fillHeight: true
        }
        AssemblyTree {
            visible: leftPanel.assembly && leftPanel.page === "tree"
            Layout.fillWidth: true; Layout.fillHeight: true
            onEditPart: leftPanel.page = "props"
        }
        AssemblyProps { visible: leftPanel.assembly && !app.sketchActive && leftPanel.page === "props"; Layout.fillWidth: true; Layout.fillHeight: true }
        Rectangle {                 // 实体的大小: 一张小卡片
            visible: !leftPanel.assembly && leftPanel.page === "tree"
            Layout.fillWidth: true
            implicitHeight: bodyInfo.implicitHeight + 18
            radius: 8
            color: Theme.cBgCard
            border.width: 1; border.color: Theme.cDivider
            Text {
                id: bodyInfo
                x: 12; y: 9
                width: parent.width - 24
                text: app.bodyText
                wrapMode: Text.Wrap
                lineHeight: 1.35
                color: Theme.cTextSec
                font.family: Theme.font; font.pixelSize: Theme.smallSize
            }
        }
    }
    Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.cDivider }
}
