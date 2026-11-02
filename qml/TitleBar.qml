// TitleBar.qml - 标题栏: 标志、文件按钮、撤销重做、设置和主题、窗口按钮; 拖它移动窗口, 双击最大化。
// 窗口用 Window.window (它所在的那个); 点 "设置" 发 openSettings (主窗口开对话框)。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Rectangle {
    id: titleBar
    signal openSettings()
    readonly property var window: Window.window
    readonly property bool maximized: window !== null && (window.visibility === Window.Maximized || window.visibility === Window.FullScreen)
    Layout.fillWidth: true
    height: 38
    color: Theme.cBgTitle

    // 拖动标题栏移动窗口, 双击最大化 / 还原。真的拖动了才开始移动: 不然最大化时单击一下窗口就缩回去
    MouseArea {
        anchors.fill: parent
        property point pressAt
        property bool moving: false
        onPressed: (mouse) => { pressAt = Qt.point(mouse.x, mouse.y); moving = false }
        onPositionChanged: (mouse) => {
            if (!pressed || moving) return
            const slop = Qt.styleHints.startDragDistance
            if (Math.abs(mouse.x - pressAt.x) < slop && Math.abs(mouse.y - pressAt.y) < slop) return
            moving = true
            titleBar.window.startSystemMove()
        }
        onDoubleClicked: app.toggleMaximize()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        spacing: 2
        Item {                      // 标志 (和任务栏上的图标是同一张) + 名字; 点它回到开始页
            implicitWidth: home.width; implicitHeight: home.height
            Layout.rightMargin: 14
            opacity: homeArea.containsMouse ? 0.75 : 1
            Row {
                id: home
                spacing: 6
                Image {
                    anchors.verticalCenter: parent.verticalCenter
                    source: "../genform/assets/genform.png"
                    sourceSize.width: 36; sourceSize.height: 36
                    width: 18; height: 18
                    smooth: true; mipmap: true
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "GenForm"
                    color: Theme.cText
                    font.family: Theme.font; font.pixelSize: 14; font.bold: true
                }
            }
            MouseArea {
                id: homeArea
                anchors.fill: parent
                hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                onClicked: app.showStart()
                Tip { shown: homeArea.containsMouse && !app.startPage; text: qsTr("开始页：新建零件 / 装配体 / 工程图，或者打开最近的文件") }
            }
        }
        IconBtn { icon: "new"; tip: qsTr("新建：零件 / 装配体 / 工程图"); action: "file.new"; onClicked: app.runAction("file.new") }
        IconBtn { icon: "open"; tip: qsTr("打开：零件 / 装配体 / 工程图"); action: "file.open"; onClicked: app.runAction("file.open") }
        IconBtn { icon: "save"; tip: qsTr("保存"); action: "file.save"; enabled: !app.startPage; onClicked: app.runAction("file.save") }
        IconBtn {
            icon: "export"; action: "file.export"; enabled: !app.startPage
            tip: app.docKind === "drawing" ? qsTr("导出：PDF / DXF / SVG / PNG")
               : (app.docKind === "assembly" ? qsTr("导出：整个装配体一个 STEP 文件") : qsTr("导出：STEP 精确几何 / STL 三角网格"))
            onClicked: app.runAction("file.export")
        }
        Rectangle { width: 1; height: 18; color: Theme.cDivider; Layout.leftMargin: 6; Layout.rightMargin: 6 }
        IconBtn { icon: "undo"; tip: qsTr("撤销"); action: "edit.undo"; enabled: app.canUndo && !app.startPage; onClicked: app.undo() }
        IconBtn { icon: "redo"; tip: qsTr("重做"); action: "edit.redo"; enabled: app.canRedo && !app.startPage; onClicked: app.redo() }
        Item { Layout.fillWidth: true }
        IconBtn { icon: "gear"; tip: qsTr("设置：快捷键、鼠标笔势（右键手势轮）、AI 接口"); action: "app.settings"; onClicked: titleBar.openSettings() }
        IconBtn { icon: "theme"; tip: Theme.darkMode ? qsTr("换成浅色界面") : qsTr("换成深色界面"); onClicked: Theme.darkMode = !Theme.darkMode }
        Item { width: 6 }
        IconBtn { objectName: "windowMinimizeButton"; icon: "min"; implicitWidth: 44; implicitHeight: 38; radius: 0; onClicked: app.minimizeWindow() }
        IconBtn { objectName: "windowMaximizeButton"; icon: titleBar.maximized ? "restore" : "max"; implicitWidth: 44; implicitHeight: 38; radius: 0; onClicked: app.toggleMaximize() }
        IconBtn { icon: "close"; danger: true; implicitWidth: 44; implicitHeight: 38; radius: 0; onClicked: titleBar.window.close() }
    }
    // 文档名放在正中 (不参与上面一行的排布, 所以不会被两边的按钮挤偏)
    Text {
        anchors.centerIn: parent
        text: app.startPage ? qsTr("开始") : app.title + (app.busy ? qsTr("　·　计算中…") : "")
        color: Theme.cTextSec
        font.family: Theme.font; font.pixelSize: Theme.smallSize
    }
}
