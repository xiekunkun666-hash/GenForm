// SketchRibbon.qml - 工具栏的草图页: 智能尺寸、画图工具 (带下拉的变体)、修改工具、几何关系、捕捉、3D 草图、快速草图。
// 工具多, 窗口窄时可以左右滚。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

Flickable {
    id: sketchRibbon
    x: 12; y: 6; height: 54
    width: parent.width - 24
    visible: app.tab === "sketch"
    contentWidth: sketchRow.implicitWidth; contentHeight: 54
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.HorizontalFlick
    interactive: contentWidth > width
    WheelHandler {
        onWheel: (event) => sketchRibbon.contentX = Math.max(0, Math.min(sketchRibbon.contentWidth - sketchRibbon.width,
                                                                        sketchRibbon.contentX - event.angleDelta.y))
    }
    RowLayout {
        id: sketchRow
        height: 54
        spacing: 1
        RibbonBtn {
            icon: app.sketchActive ? "exit" : "sketch"
            text: app.sketchActive ? qsTr("退出草图") : qsTr("草图绘制")
            active: app.sketchActive
            tip: app.sketchActive ? qsTr("退出草图：保存这个草图并退出") : qsTr("草图绘制：选一个基准面或零件上的一个平面，在它上面画草图")
            action: app.sketchActive ? "sketch.finish" : "sketch.start"
            onClicked: app.startSketch()
        }
        RibbonSeparator {}
        RibbonBtn { enabled: app.sketchActive; icon: "dimension"; text: qsTr("智能尺寸"); tip: qsTr("智能尺寸：点一个图形改它的尺寸；再点另一个图形 = 改它们之间的距离"); action: "tool:dimension"; active: app.sketchTool === "dimension"; onClicked: app.useSketchTool("dimension") }
        RibbonSeparator {}
        RibbonMenu {
            icon: "line"; text: qsTr("直线"); tip: qsTr("直线：直线、中心线、中点线"); action: "tool:line"
            active: ["line", "centerline", "midline"].indexOf(app.sketchTool) >= 0
            items: [{id: "line", title: qsTr("直线")}, {id: "centerline", title: qsTr("中心线")}, {id: "midline", title: qsTr("中点线")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonMenu {
            icon: "rect"; text: qsTr("矩形"); tip: qsTr("矩形：边角矩形、中心矩形、3 点边角矩形、3 点中心矩形、平行四边形、多边形"); action: "tool:rect"
            active: ["rect", "crect", "rect3", "crect3", "pgram", "ngon"].indexOf(app.sketchTool) >= 0
            items: [{id: "rect", title: qsTr("边角矩形")}, {id: "crect", title: qsTr("中心矩形")}, {id: "rect3", title: qsTr("3 点边角矩形")},
                    {id: "crect3", title: qsTr("3 点中心矩形")}, {id: "pgram", title: qsTr("平行四边形")}, {id: "ngon", title: qsTr("多边形")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonMenu {
            icon: "slot"; text: qsTr("槽口"); tip: qsTr("直槽口、中心点直槽口、三点圆弧槽口、中心点圆弧槽口")
            active: ["slot", "cslot", "aslot3", "caslot"].indexOf(app.sketchTool) >= 0
            items: [{id: "slot", title: qsTr("直槽口")}, {id: "cslot", title: qsTr("中心点直槽口")}, {id: "aslot3", title: qsTr("三点圆弧槽口")},
                    {id: "caslot", title: qsTr("中心点圆弧槽口")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonMenu {
            icon: "circle"; text: qsTr("圆"); tip: qsTr("圆：圆心 + 半径；周边圆：圆周上三个点；椭圆：中心 → 长轴 → 短轴"); action: "tool:circle"
            active: ["circle", "circle3", "ellipse"].indexOf(app.sketchTool) >= 0
            items: [{id: "circle", title: qsTr("圆")}, {id: "circle3", title: qsTr("周边圆")}, {id: "ellipse", title: qsTr("椭圆")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonBtn { icon: "arc"; text: qsTr("圆弧"); tip: qsTr("圆弧：圆心/起/终点画弧"); action: "tool:arc"; active: app.sketchTool === "arc"; onClicked: app.useSketchTool("arc") }
        RibbonMenu {
            icon: "spline"; text: qsTr("样条"); tip: qsTr("样条曲线、样式样条曲线、方程式驱动的曲线")
            active: ["spline", "sspline", "equation"].indexOf(app.sketchTool) >= 0
            items: [{id: "spline", title: qsTr("样条曲线")}, {id: "sspline", title: qsTr("样式样条曲线")}, {id: "equation", title: qsTr("方程式驱动的曲线")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonBtn { icon: "point"; text: qsTr("点"); tip: qsTr("绘制一个点：单击放置"); active: app.sketchTool === "point"; onClicked: app.useSketchTool("point") }
        RibbonBtn { icon: "text"; text: qsTr("文本"); tip: qsTr("单击放置一行字；先选中一条曲线再点这里 = 沿这条曲线排"); active: app.sketchTool === "text"; onClicked: app.useSketchTool("text") }
        RibbonSeparator {}
        RibbonBtn { enabled: app.sketchActive; icon: "fillet"; text: qsTr("圆角"); tip: qsTr("绘制圆角：点两条直线相交的尖角"); active: app.sketchTool === "fillet"; onClicked: app.useSketchTool("fillet") }
        RibbonMenu {
            enabled: app.sketchActive
            icon: "trim"; text: qsTr("剪裁"); tip: qsTr("剪裁实体：点要剪掉的那一段；延伸实体：点要延长的那一头"); action: "tool:trim"
            active: ["trim", "extend"].indexOf(app.sketchTool) >= 0
            items: [{id: "trim", title: qsTr("剪裁实体")}, {id: "extend", title: qsTr("延伸实体")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonBtn { enabled: app.sketchActive; icon: "offset"; text: qsTr("等距"); tip: qsTr("等距实体：点一个图形，再点一下定距离和方向"); action: "tool:offset"; active: app.sketchTool === "offset"; onClicked: app.useSketchTool("offset") }
        RibbonBtn { enabled: app.sketchActive; icon: "mirror"; text: qsTr("镜向"); tip: qsTr("镜向实体：先选图形，再点两点定镜向轴"); active: app.sketchTool === "mirror"; onClicked: app.useSketchTool("mirror") }
        RibbonMenu {
            enabled: app.sketchActive
            icon: "pattern"; text: qsTr("阵列"); tip: qsTr("先选图形。线性草图阵列：填数量和间距；圆周草图阵列：填数量、总角度和中心")
            active: app.sketchOperation === "pattern" || app.sketchOperation === "cpattern"
            items: [{id: "pattern", title: qsTr("线性草图阵列")}, {id: "cpattern", title: qsTr("圆周草图阵列")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonBtn { enabled: app.sketchActive; icon: "move"; text: qsTr("移动"); tip: qsTr("移动实体：先选图形，再点起点和终点"); action: "tool:move"; active: app.sketchTool === "move"; onClicked: app.useSketchTool("move") }
        RibbonMenu {
            enabled: app.sketchActive
            icon: "convert"; text: qsTr("转换引用"); tip: qsTr("转换实体引用：把实体的边拷进草图；侧影实体：曲面转过去的轮廓线；交叉曲线：草图平面切开实体的交线")
            active: app.sketchTool === "convert"
            items: [{id: "convert", title: qsTr("转换实体引用")}, {id: "silhouette", title: qsTr("侧影实体")}, {id: "section", title: qsTr("交叉曲线")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonSeparator {}
        RibbonMenu {
            enabled: app.sketchActive
            icon: "relation"; text: qsTr("几何关系"); tip: qsTr("添加几何关系：先选图形（第一个不动），再选水平 / 竖直 / 平行 / 垂直 / 相等 / 同心 / 相切…；修复草图：找出废线、重复的线、没接上的端点")
            active: app.sketchOperation === "relation" || app.sketchOperation === "repair"
            items: [{id: "relation", title: qsTr("添加几何关系")}, {id: "repair", title: qsTr("修复草图")}]
            onPicked: (id) => app.sketchPick(id)
        }
        RibbonBtn {
            id: snapButton
            icon: "snap"; text: qsTr("捕捉")
            tip: qsTr("捕捉：每一种可以单独开关；右边一列是快速捕捉（下一次点击只吸到这一种点）")
            active: app.quickSnap !== ""
            onClicked: snapMenu.opened ? snapMenu.close() : snapMenu.open()
            Popup {
                id: snapMenu
                y: parent.height + 6
                padding: 8
                onAboutToShow: x = Math.min(0, Window.width - 8 - snapButton.mapToItem(null, 0, 0).x - implicitWidth)
                background: Rectangle { color: Theme.cBg; radius: 8; border.width: 1; border.color: Theme.cDivider }
                contentItem: Row {
                    spacing: 8
                    Column {
                        spacing: 2
                        Text { x: 8; height: 24; verticalAlignment: Text.AlignVCenter; text: qsTr("一直开着"); color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.textSize - 1 }
                        Repeater {
                            model: app.snapToggles
                            delegate: Rectangle {
                                required property var modelData
                                width: 150; height: 30; radius: 5
                                color: toggleArea.containsMouse ? Theme.cBgHover : "transparent"
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    x: 10; width: 16
                                    text: modelData.on ? "✓" : ""
                                    color: Theme.cAccent
                                    font.family: Theme.font; font.pixelSize: Theme.textSize
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    x: 30
                                    text: modelData.text
                                    color: modelData.on ? Theme.cText : Theme.cTextMuted
                                    font.family: Theme.font; font.pixelSize: Theme.textSize
                                }
                                MouseArea {
                                    id: toggleArea
                                    anchors.fill: parent; hoverEnabled: true
                                    onClicked: app.toggleSnap(modelData.id)
                                }
                            }
                        }
                    }
                    Rectangle { width: 1; height: parent.height; color: Theme.cDivider }
                    Column {
                        spacing: 2
                        Text { x: 8; height: 24; verticalAlignment: Text.AlignVCenter; text: qsTr("只用一次"); color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.textSize - 1 }
                        Repeater {
                            model: app.quickSnaps
                            delegate: Rectangle {
                                required property var modelData
                                readonly property bool on: app.quickSnap === modelData.id
                                width: 138; height: 30; radius: 5
                                opacity: app.sketchActive ? 1 : 0.45
                                color: on ? Theme.cAccentSoft : (snapArea.containsMouse ? Theme.cBgHover : "transparent")
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    x: 12
                                    text: modelData.text
                                    color: parent.on ? Theme.cAccent : Theme.cText
                                    font.family: Theme.font; font.pixelSize: Theme.textSize
                                }
                                MouseArea {
                                    id: snapArea
                                    anchors.fill: parent; hoverEnabled: true
                                    onClicked: { app.setQuickSnap(modelData.id); snapMenu.close() }
                                }
                            }
                        }
                    }
                }
            }
        }
        RibbonMenu { icon: "sketch3d"; text: qsTr("3D 草图"); tip: qsTr("3D 草图：按空间坐标点连成的线；曲面上的样条曲线：贴在一张面上的样条"); items: app.featureMenus[4].items; onPicked: (id) => app.startCommand(id) }
        RibbonBtn { icon: "rapid"; text: qsTr("快速草图"); tip: qsTr("快速草图：进草图不转视角，画完一个接着点下一个基准面"); active: app.rapidSketch; onClicked: app.toggleRapidSketch() }
        RibbonSeparator { visible: app.sketchActive }
        RibbonBtn { visible: app.sketchActive; icon: "select"; text: qsTr("选择"); tip: qsTr("选择：选中、移动、改形状（按 Esc 也回到这里）"); active: app.sketchTool === "select" && app.sketchOperation === ""; onClicked: app.useSketchTool("select") }
    }
}
