// Tip.qml - 悬停说明: 深色的小卡片, 标题加粗, 右边带快捷键的键帽, 下面是一两句说明。
// 用法: 放在按钮里, shown 绑到 "鼠标在上面"。text 写成 "标题：说明" 的话, 冒号前面的当标题。
import QtQuick
import QtQuick.Controls.Basic

ToolTip {
    id: tip
    property bool shown: false
    property string keys: ""            // 这个功能的快捷键 (没有就不显示键帽)
    property bool above: false          // 摆在按钮上面 (默认在下面)
    readonly property int cut: text.indexOf("：")
    readonly property string head: cut > 0 && cut <= 16 ? text.substring(0, cut) : ""
    readonly property string body: head !== "" ? text.substring(cut + 1) : text

    visible: shown && text !== ""
    delay: 380
    timeout: -1
    padding: 0
    margins: 6
    x: parent ? Math.round((parent.width - implicitWidth) / 2) : 0
    y: parent ? (above ? -implicitHeight - 8 : parent.height + 8) : 0

    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 110 } }
    exit: Transition { NumberAnimation { property: "opacity"; from: 1; to: 0; duration: 70 } }

    background: Item {
        Rectangle {                     // 一圈淡淡的影子
            anchors.fill: parent; anchors.margins: -1
            anchors.topMargin: 1; anchors.bottomMargin: -3
            radius: 10
            color: "#000000"; opacity: 0.22
        }
        Rectangle {
            anchors.fill: parent
            radius: 8
            color: Theme.cTipBg
            border.width: 1; border.color: Theme.cTipLine
        }
        Rectangle {                     // 左边一条蓝色的细边: 点缀
            x: 1; y: 8; width: 2; height: parent.height - 16; radius: 1
            color: Theme.cAccent
            visible: tip.head !== ""
        }
    }
    contentItem: Column {
        padding: 9; leftPadding: 13; rightPadding: 12
        spacing: 4
        Row {
            spacing: 10
            visible: tip.head !== "" || tip.keys !== ""
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: tip.head !== "" ? tip.head : tip.body
                color: Theme.cTipText
                font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true
            }
            Rectangle {                 // 键帽
                anchors.verticalCenter: parent.verticalCenter
                visible: tip.keys !== ""
                width: keyText.implicitWidth + 12; height: 18; radius: 4
                color: Theme.cTipKey
                border.width: 1; border.color: Theme.cTipLine
                Text {
                    id: keyText
                    anchors.centerIn: parent
                    text: tip.keys
                    color: Theme.cTipText
                    font.family: Theme.font; font.pixelSize: 11
                }
            }
        }
        Text {
            visible: !(tip.head === "" && tip.keys !== "") && text !== ""
            width: Math.min(implicitWidth, 300)
            text: tip.body
            wrapMode: Text.Wrap
            lineHeight: 1.25
            color: tip.head !== "" ? Theme.cTipSub : Theme.cTipText
            font.family: Theme.font; font.pixelSize: Theme.smallSize
        }
    }
}
