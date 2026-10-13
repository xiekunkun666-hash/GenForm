// MenuList.qml - 下拉菜单: 每项一个图标 + 文字, 可以带勾 (开关项) 和分隔线。点一项 → picked(id)
import QtQuick
import QtQuick.Controls

Popup {
    id: menu
    property var items: []              // [{id, title, icon (不写就用 id 当图标名), checked (开关项才有), line (这一项上面画分隔线)}...]
    property string current: ""         // 单选的菜单: 现在选着的那一项的 id
    property bool keepOpen: false       // 点了不关 (一串开关项连着点)
    property real itemWidth: 196
    property Item anchorItem: null      // 菜单挂在谁下面: 靠窗口右边时往左挪, 不伸到窗口外面去
    signal picked(string id)

    padding: 6
    background: Rectangle { color: Theme.cBgCard; radius: 9; border.width: 1; border.color: Theme.cDivider }
    onAboutToShow: if (anchorItem) x = Math.min(0, anchorItem.Window.width - 8 - anchorItem.mapToItem(null, 0, 0).x - implicitWidth)

    contentItem: Column {
        spacing: 2
        Repeater {
            model: menu.items
            delegate: Column {
                id: entry
                required property var modelData
                readonly property bool on: modelData.checked === true || (menu.current !== "" && menu.current === modelData.id)
                spacing: 2
                Item {
                    visible: entry.modelData.line === true
                    width: menu.itemWidth; height: 7
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; x: 6; width: parent.width - 12; height: 1; color: Theme.cDivider }
                }
                Rectangle {
                    width: menu.itemWidth; height: 30; radius: 6
                    color: itemArea.containsMouse ? Theme.cBgHover : (entry.on ? Theme.cAccentSoft : "transparent")
                    Icon {
                        x: 9
                        anchors.verticalCenter: parent.verticalCenter
                        size: 18
                        name: entry.modelData.icon || entry.modelData.id
                        color: entry.on || itemArea.containsMouse ? Theme.cAccent : Theme.cIcon
                    }
                    Text {
                        x: 36
                        width: parent.width - 36 - 26
                        anchors.verticalCenter: parent.verticalCenter
                        text: entry.modelData.title
                        elide: Text.ElideRight
                        color: Theme.cText
                        font.family: Theme.font; font.pixelSize: Theme.textSize
                    }
                    Icon {
                        visible: entry.modelData.checked === true
                        anchors.right: parent.right; anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        size: 14; name: "check"; color: Theme.cAccent
                    }
                    MouseArea {
                        id: itemArea
                        anchors.fill: parent; hoverEnabled: true
                        onClicked: { if (!menu.keepOpen) menu.close(); menu.picked(entry.modelData.id) }
                    }
                }
            }
        }
    }
}
