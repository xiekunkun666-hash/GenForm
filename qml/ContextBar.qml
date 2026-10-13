// ContextBar.qml - 点一个特征 / 草图 / 面弹出来的一排小按钮 (和 SOLIDWORKS 的关联工具栏一个意思):
// 编辑特征、编辑草图、压缩、退回、隐藏/显示、放大所选范围、正视于、外观… 按钮由控制器给 (app.featureContext / app.sceneContext)。
import QtQuick
import QtQuick.Controls

Popup {
    id: bar
    property var items: []              // [{id, icon, title, tip}...]
    property string target: ""          // 特征 id (在视图里点了不属于任何特征的面时是空的)
    padding: 4
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { color: Theme.cBgCard; radius: 9; border.width: 1; border.color: Theme.cAccentLine }
    enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 90 } }

    function pick(action) {
        if (action === "sketch_plane") {            // 编辑草图平面: 再弹一个菜单选基准面
            planeMenu.items = app.planeChoices(bar.target)
            planeMenu.open()
            return
        }
        const stay = ["zoom", "normal", "select_other", "back_face", "same_faces"].indexOf(action) >= 0
        const target = bar.target
        if (!stay) bar.close()
        app.contextAction(target, action)
    }

    contentItem: Grid {
        columns: Math.max(1, Math.min(bar.items.length, 8))
        spacing: 2
        Repeater {
            model: bar.items
            delegate: IconBtn {
                required property var modelData
                icon: modelData.icon
                iconSize: 19
                tint: Theme.cIcon
                tip: modelData.tip
                onClicked: bar.pick(modelData.id)
            }
        }
    }
    MenuList {
        id: planeMenu
        y: parent ? parent.height + 8 : 0
        itemWidth: 180
        onPicked: (id) => { const target = bar.target; bar.close(); app.setSketchPlane(target, id) }
    }
}
