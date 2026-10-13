// RibbonMenu.qml - 工具栏上带下拉菜单的大按钮 (阵列、参考几何体、曲线这类一组命令)。点开选一项 → picked(id)
import QtQuick
import QtQuick.Controls

RibbonBtn {
    id: button
    property var items: []          // [{id, title, icon}...]: 没写 icon 的用 id 当图标名
    signal picked(string id)
    text: ""
    onClicked: menu.opened ? menu.close() : menu.open()

    Text {                          // 右上角的小三角: 这是个菜单
        anchors.right: parent.right; anchors.rightMargin: 4
        anchors.top: parent.top; anchors.topMargin: 10
        text: "▾"
        color: Theme.cTextMuted
        font.pixelSize: 10
    }
    MenuList {
        id: menu
        y: parent.height + 6
        items: button.items
        anchorItem: button
        onPicked: (id) => button.picked(id)
    }
}
