// ViewLabels.qml - 视图里的文字: 基准面的名字、草图的尺寸; 装配体实时检查的红叉 (kind "clash", x / y 是叉的中心);
// 草图里的几何关系小图标 (kind "relation") 和智能尺寸的数字
// (kind "dim"), 这两种 x / y 是中心, 点它 = 选中 (属性管理器里能删, 也可以按 Delete)。view 是它标在上面的 Viewport。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Repeater {
    id: labels
    property var view: null
    model: labels.view ? labels.view.labels : []
    delegate: Rectangle {
        required property var modelData
        readonly property bool size: modelData.kind === "size"
        readonly property bool relation: modelData.kind === "relation"
        readonly property bool dim: modelData.kind === "dim"          // 智能尺寸的数字: 压在尺寸线中间, 点它选中
        readonly property bool clash: modelData.kind === "clash"         // 两个零件压进去了: 红叉 + 哪两个件
        readonly property bool centred: relation || dim
        readonly property bool pickable: centred && !!modelData.id
        readonly property bool chosen: centred && modelData.chosen === true
        readonly property bool lit: chosen || modelData.hot === true || (pickable && badgeArea.containsMouse)
        x: clash ? modelData.x - 11 : centred ? modelData.x - width / 2 : modelData.x
        y: clash ? modelData.y - 11 : centred ? modelData.y - height / 2 : modelData.y
        width: clash ? clashRow.implicitWidth : relation ? relationRow.implicitWidth + 6 : labelText.implicitWidth + (size || dim ? 12 : 0)
        height: clash ? 22 : relation ? 17 : labelText.implicitHeight + (size || dim ? 6 : 0)
        radius: 4
        color: clash ? "transparent" : chosen ? Theme.cAccentStrong
             : size || centred ? Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, relation ? 0.8 : 0.88) : "transparent"
        border.width: clash ? 0 : dim ? (lit ? 1.5 : 0) : size || relation ? (lit ? 1.5 : 1) : 0
        border.color: lit ? Theme.cAccent : relation ? Qt.rgba(Theme.cAxisY.r, Theme.cAxisY.g, Theme.cAxisY.b, 0.55) : Theme.cDivider
        scale: lit ? 1.15 : 1.0
        Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
        MouseArea {                     // 只给关系图标: 点一下选中。尺寸的数字不接鼠标 (悬停、按下、拖都交给底下的视图,
            id: badgeArea               // 草图编辑器自己认出是哪个尺寸; 这里的文字每帧重建, 自己接会断, 还会挡住视图的悬停)
            enabled: parent.pickable && !parent.dim
            anchors.fill: parent; anchors.margins: -3
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: app.selectSketchRelation(modelData.id)
        }
        Text {
            id: labelText
            visible: !relation && !clash
            anchors.centerIn: parent
            text: app.tr(modelData.text)
            color: chosen ? "#FFFFFF" : size || dim ? Theme.cText : Theme.cAccent
            opacity: size || dim ? 1.0 : 0.85
            font.family: Theme.font; font.pixelSize: dim ? Theme.textSize : size ? Theme.smallSize : 11
        }
        Row {                   // 干涉: 红底白叉, 旁边写哪两个件、压进去多深
            id: clashRow
            visible: clash
            spacing: 6
            Rectangle {
                width: 22; height: 22; radius: 11
                color: Theme.cError
                border.width: 2; border.color: "#FFFFFF"
                Icon { anchors.centerIn: parent; name: "close"; size: 13; color: "#FFFFFF" }
            }
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: clashText.implicitWidth + 12; height: clashText.implicitHeight + 6; radius: 4
                color: Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.9)
                border.width: 1; border.color: Theme.cError
                Text {
                    id: clashText
                    anchors.centerIn: parent
                    text: clash ? modelData.text : ""
                    color: Theme.cError
                    font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true
                }
            }
        }
        Row {                   // 几何关系: 小图标 (+ 相等的组号)
            id: relationRow
            visible: relation
            anchors.centerIn: parent
            spacing: 1
            Icon { anchors.verticalCenter: parent.verticalCenter; name: relation ? modelData.icon : ""; size: 13; color: chosen ? "#FFFFFF" : Theme.cAxisY }
            Text {
                visible: relation && modelData.text !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: relation ? modelData.text : ""
                color: Theme.cAxisY
                font.family: Theme.font; font.pixelSize: 10; font.bold: true
            }
        }
    }
}
