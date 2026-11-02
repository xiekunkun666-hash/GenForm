// FeatureRibbon.qml - 工具栏的特征页 (和 SOLIDWORKS 的特征页一个顺序: 凸台 | 切除和孔 | 修改 | 阵列、参考几何体、曲线)。
// 窗口窄时可以左右滚。
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Flickable {
    id: featureRibbon
    x: 12; y: 6; height: 54
    width: parent.width - 24
    visible: app.tab === "feature"
    contentWidth: featureRow.implicitWidth; contentHeight: 54
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    flickableDirection: Flickable.HorizontalFlick
    interactive: contentWidth > width
    WheelHandler {
        onWheel: (event) => featureRibbon.contentX = Math.max(0, Math.min(featureRibbon.contentWidth - featureRibbon.width,
                                                                          featureRibbon.contentX - event.angleDelta.y))
    }
    RowLayout {
        id: featureRow
        height: 54
        spacing: 1
        RibbonBtn { icon: "extrude"; text: qsTr("拉伸凸台"); tip: qsTr("拉伸凸台/基体：把草图拉伸成实体。正在画草图时点它：先保存草图，接着就拉伸它"); action: "cmd:extrude"; onClicked: app.startCommand("extrude") }
        RibbonBtn { icon: "revolve"; text: qsTr("旋转凸台"); tip: qsTr("旋转凸台/基体：把草图绕一根轴旋转成实体"); onClicked: app.startCommand("revolve") }
        RibbonBtn { icon: "sweep"; text: qsTr("扫描"); tip: qsTr("让轮廓草图沿一条路径 (草图或曲线) 扫过去"); onClicked: app.startCommand("sweep") }
        RibbonBtn { icon: "loft"; text: qsTr("放样凸台"); tip: qsTr("放样凸台/基体：在几个草图轮廓之间过渡"); onClicked: app.startCommand("loft") }
        RibbonBtn { icon: "boundary"; text: qsTr("边界凸台"); tip: qsTr("边界凸台/基体：轮廓之间光顺过渡 (目前只有方向 1)"); onClicked: app.startCommand("boundary") }
        RibbonSeparator {}
        RibbonBtn { icon: "cut"; text: qsTr("拉伸切除"); tip: qsTr("用草图从实体上切掉一块"); onClicked: app.startCommand("cut") }
        RibbonMenu { icon: "hole"; text: qsTr("异形孔"); tip: qsTr("异形孔向导、高级孔、螺纹线、螺柱向导"); items: app.featureMenus[0].items; onPicked: (id) => app.startCommand(id) }
        RibbonBtn { icon: "revolve"; text: qsTr("旋转切除"); tip: qsTr("把草图绕轴旋转, 从实体上切掉"); onClicked: app.startCommand("revolve_cut") }
        RibbonBtn { icon: "sweep"; text: qsTr("扫描切除"); tip: qsTr("轮廓沿路径扫过去, 从实体上切掉"); onClicked: app.startCommand("sweep_cut") }
        RibbonBtn { icon: "loft"; text: qsTr("放样切除"); tip: qsTr("在几个轮廓之间过渡, 从实体上切掉"); onClicked: app.startCommand("loft_cut") }
        RibbonSeparator {}
        RibbonBtn { objectName: "featureCommand_fillet"; icon: "fillet"; text: qsTr("圆角"); tip: qsTr("圆角：给选中的边倒圆角"); action: "cmd:fillet"; onClicked: app.startCommand("fillet") }
        RibbonBtn { objectName: "featureCommand_chamfer"; icon: "chamfer"; text: qsTr("倒角"); tip: qsTr("给选中的边倒斜角"); onClicked: app.startCommand("chamfer") }
        RibbonBtn { icon: "rib"; text: qsTr("筋"); tip: qsTr("用一条开口的草图线做加强筋"); onClicked: app.startCommand("rib") }
        RibbonBtn { icon: "draft"; text: qsTr("拔模"); tip: qsTr("把选中的面相对中性面倾斜一个角度"); onClicked: app.startCommand("draft") }
        RibbonBtn { icon: "shell"; text: qsTr("抽壳"); tip: qsTr("掏空成等厚的壳, 选中的面成为开口"); onClicked: app.startCommand("shell") }
        RibbonBtn { icon: "wrap"; text: qsTr("包裹"); tip: qsTr("把草图轮廓贴到圆柱面上, 凸起或凹进"); onClicked: app.startCommand("wrap") }
        RibbonBtn { icon: "mirror"; text: qsTr("镜像"); tip: qsTr("关于一个基准面镜像特征或整个实体"); onClicked: app.startCommand("mirror") }
        RibbonSeparator {}
        RibbonMenu { icon: "pattern"; text: qsTr("阵列"); tip: qsTr("线性、圆周、镜像、曲线驱动、草图驱动、表格驱动、填充、变量阵列"); items: app.featureMenus[1].items; onPicked: (id) => app.startCommand(id) }
        RibbonMenu { icon: "reference"; text: qsTr("参考几何体"); tip: qsTr("基准面、基准轴、坐标系、点、质心、边界框"); items: app.featureMenus[2].items; onPicked: (id) => app.startCommand(id) }
        RibbonMenu { icon: "curve"; text: qsTr("曲线"); tip: qsTr("分割线、投影曲线、组合曲线、通过点的曲线、螺旋线/涡状线"); items: app.featureMenus[3].items; onPicked: (id) => app.startCommand(id) }
        RibbonMenu { icon: "sketch3d"; text: qsTr("3D 草图"); tip: qsTr("3D 草图、曲面上的样条曲线"); items: app.featureMenus[4].items; onPicked: (id) => app.startCommand(id) }
    }
}
