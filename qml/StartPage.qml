// StartPage.qml - 开始页: 刚打开软件时先选新建哪一种文档 (零件 / 装配体 / 工程图), 或者打开文件、最近用过的文件
// 盖住标题栏下面的整个窗口; 选了以后淡出, 进到那个文档。点标题栏左上角的标志可以回来。
import QtQuick
import QtQuick.Controls

Rectangle {
    id: page
    signal openRequested()
    color: Theme.cBg
    opacity: app.startPage ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    // 开着时挡住下面的视图: 鼠标、滚轮都不漏下去
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = true }

    readonly property var kinds: ({ part: "cube", assembly: "assembly", drawing: "drawing" })
    readonly property var kindNames: ({ part: qsTr("零件"), assembly: qsTr("装配体"), drawing: qsTr("工程图") })

    Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, body.height + 80)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar {}

        Column {
            id: body
            width: Math.min(parent.width - 64, 3 * 220 + 2 * 20)
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(40, (page.height - height) * 0.38)
            spacing: 18
            // 进来时整块从下面浮上来一点
            transform: Translate { y: app.startPage ? 0 : 16; Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } } }

            Column {
                spacing: 6
                Text { text: qsTr("新建"); color: Theme.cText; font.family: Theme.font; font.pixelSize: 22; font.bold: true }
                Text { text: qsTr("选一种文档开始；也可以把文件拖进窗口直接打开"); color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            }

            Row {
                spacing: 20
                Repeater {
                    model: [{ id: "part", icon: "cube", title: qsTr("零件"), text: qsTr("一个实体：画草图，再拉伸、切除、倒角…") },
                            { id: "assembly", icon: "assembly", title: qsTr("装配体"), text: qsTr("把几个零件摆到一起，查干涉、装配顺序，做运动副和动画") },
                            { id: "drawing", icon: "drawing", title: qsTr("工程图"), text: qsTr("零件的三视图排在图纸上，标尺寸，导出 PDF / DXF") }]
                    delegate: Rectangle {
                        id: card
                        required property var modelData
                        width: (body.width - 40) / 3; height: 210; radius: 12
                        color: cardArea.containsMouse ? Theme.cAccentSoft : Theme.cBgCard
                        border.width: cardArea.containsMouse ? 1.5 : 1
                        border.color: cardArea.containsMouse ? Theme.cAccent : Theme.cDivider
                        scale: cardArea.pressed ? 0.97 : (cardArea.containsMouse ? 1.02 : 1)
                        Behavior on color { ColorAnimation { duration: 140 } }
                        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                        Icon {
                            anchors.horizontalCenter: parent.horizontalCenter; y: 30; size: 60
                            name: card.modelData.icon; color: cardArea.containsMouse ? Theme.cAccent : Theme.cIcon
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter; y: 108
                            text: card.modelData.title
                            color: Theme.cText; font.family: Theme.font; font.pixelSize: 16; font.bold: true
                        }
                        Text {
                            x: 18; y: 138; width: parent.width - 36
                            horizontalAlignment: Text.AlignHCenter; wrapMode: Text.Wrap
                            text: card.modelData.text
                            color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize; lineHeight: 1.25
                        }
                        MouseArea {
                            id: cardArea
                            anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: app.newOf(card.modelData.id)
                        }
                    }
                }
            }

            Item { width: 1; height: 8 }

            // ---- 最近的文件 ----
            Item {
                width: body.width; height: 30
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: qsTr("最近打开"); color: Theme.cText; font.family: Theme.font; font.pixelSize: 15; font.bold: true
                }
                Rectangle {
                    id: openButton
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    width: openRow.width + 24; height: 30; radius: 6
                    color: openArea.containsMouse ? Theme.cBgHover : Theme.cBgInput
                    border.width: 1; border.color: openArea.containsMouse ? Theme.cAccent : Theme.cDivider
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Row {
                        id: openRow
                        anchors.centerIn: parent; spacing: 6
                        Icon { anchors.verticalCenter: parent.verticalCenter; size: 16; name: "open"; color: Theme.cIcon }
                        Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("打开文件…"); color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
                    }
                    MouseArea { id: openArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: page.openRequested() }
                }
            }

            Rectangle {
                width: body.width
                height: app.recentFiles.length ? recentList.height + 8 : 64
                radius: 10; color: Theme.cBgCard; border.width: 1; border.color: Theme.cDivider
                Text {
                    anchors.centerIn: parent
                    visible: app.recentFiles.length === 0
                    text: qsTr("还没有打开过文件")
                    color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize
                }
                Column {
                    id: recentList
                    x: 4; y: 4; width: parent.width - 8
                    Repeater {
                        model: app.recentFiles
                        delegate: Rectangle {
                            id: row
                            required property var modelData
                            width: recentList.width; height: 44; radius: 7
                            color: rowHover.hovered ? Theme.cBgHover : "transparent"
                            Behavior on color { ColorAnimation { duration: 100 } }
                            Icon { x: 12; anchors.verticalCenter: parent.verticalCenter; size: 20; name: page.kinds[row.modelData.kind]; color: rowHover.hovered ? Theme.cAccent : Theme.cIcon }
                            Column {
                                x: 44; anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - 44 - 220
                                Text { width: parent.width; elide: Text.ElideRight; text: row.modelData.name; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
                                Text { width: parent.width; elide: Text.ElideMiddle; text: row.modelData.folder; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11 }
                            }
                            Text {
                                anchors.right: parent.right; anchors.rightMargin: 44; anchors.verticalCenter: parent.verticalCenter
                                text: page.kindNames[row.modelData.kind] + "　" + row.modelData.time
                                color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11
                            }
                            HoverHandler { id: rowHover }      // 悬停在去掉按钮上也算在这一行里
                            MouseArea { id: rowArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: app.openDocument(row.modelData.path) }
                            IconBtn {      // 从列表里去掉 (文件不删)
                                anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                                visible: rowHover.hovered
                                icon: "close"; iconSize: 12; tip: qsTr("从最近列表里去掉（文件不删）")
                                onClicked: app.forgetRecent(row.modelData.path)
                            }
                        }
                    }
                }
            }
        }
    }
}
