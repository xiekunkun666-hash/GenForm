// ViewBar.qml - 浮在三维视图上方正中的一排小按钮 (和 SOLIDWORKS 的前导视图工具栏一个意思):
// 整屏显示全图 | 局部放大 | 上一个视图 | 剖切视图 || 视图定向 ▾ | 显示样式 ▾ | 隐藏/显示项目 ▾ || 编辑外观 | 应用布景 ▾ | 视图设定 ▾
import QtQuick
import QtQuick.Controls

Rectangle {
    id: bar
    property var view                   // 三维视图 (Viewport)
    readonly property var state: app.viewState
    function openAppearance() { lookPop.open() }
    height: 38
    width: row.implicitWidth + 12
    radius: 10
    color: Qt.rgba(Theme.cBgCard.r, Theme.cBgCard.g, Theme.cBgCard.b, 0.94)
    border.width: 1; border.color: Theme.cDivider
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = true }   // 点在条上不漏到视图里

    component Gap: Rectangle { width: 1; height: 18; color: Theme.cDivider; anchors.verticalCenter: parent ? parent.verticalCenter : undefined }
    component MenuBtn: IconBtn {
        id: opener
        property var items: []
        property string current: ""
        property bool keepOpen: false
        property real itemWidth: 190
        signal picked(string id)
        implicitWidth: 42
        iconSize: 19
        active: list.opened
        onClicked: list.opened ? list.close() : list.open()
        Text { anchors.right: parent.right; anchors.rightMargin: 2; anchors.bottom: parent.bottom; anchors.bottomMargin: 3; text: "▾"; color: Theme.cTextMuted; font.pixelSize: 9 }
        MenuList {
            id: list
            y: opener.height + 9
            items: opener.items; current: opener.current; keepOpen: opener.keepOpen; itemWidth: opener.itemWidth
            anchorItem: opener
            onPicked: (id) => opener.picked(id)
        }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 1

        IconBtn { icon: "fit"; iconSize: 19; tip: qsTr("整屏显示全图：把内容放满画面"); onClicked: app.viewAction("fit") }
        IconBtn { icon: "zoom_box"; iconSize: 19; tip: qsTr("局部放大：拖一个框，框里的内容放满画面"); active: bar.view ? bar.view.zoomArmed : false; onClicked: app.viewAction("zoom_box") }
        IconBtn { icon: "previous"; iconSize: 19; tip: qsTr("上一个视图：回到刚才的视角"); onClicked: app.viewAction("previous") }
        IconBtn {
            id: sectionBtn
            icon: "section"; iconSize: 19
            tip: qsTr("剖切视图：用一个基准面把零件切开看里面")
            active: bar.state.section || sectionPop.opened
            onClicked: sectionPop.opened ? sectionPop.close() : sectionPop.open()
            Popup {
                id: sectionPop
                y: sectionBtn.height + 9
                padding: 12
                background: Rectangle { color: Theme.cBgCard; radius: 9; border.width: 1; border.color: Theme.cDivider }
                contentItem: Column {
                    spacing: 10
                    Text { text: qsTr("剖切视图"); color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
                    Row {
                        spacing: 4
                        Repeater {
                            model: [{ id: "XZ", text: qsTr("前视基准面"), icon: "front" }, { id: "XY", text: qsTr("上视基准面"), icon: "top" }, { id: "YZ", text: qsTr("右视基准面"), icon: "right" }]
                            delegate: IconBtn {
                                required property var modelData
                                icon: modelData.icon; iconSize: 19; tint: Theme.cIcon
                                tip: qsTr("用%1切").arg(modelData.text)
                                active: bar.state.section && bar.state.sectionPlane === modelData.id
                                onClicked: app.setSection(modelData.id, bar.state.sectionOffset)
                            }
                        }
                    }
                    Row {
                        spacing: 6
                        Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("偏移"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                        ToolBtn { compact: true; text: "−"; onClicked: app.setSection(bar.state.sectionPlane, bar.state.sectionOffset - 5) }
                        Rectangle {
                            width: 78; height: 26; radius: 5
                            color: Theme.cBgInput
                            border.width: 1; border.color: offsetInput.activeFocus ? Theme.cAccent : Theme.cDivider
                            TextInput {
                                id: offsetInput
                                anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 28
                                verticalAlignment: TextInput.AlignVCenter; horizontalAlignment: TextInput.AlignRight
                                text: Number(bar.state.sectionOffset).toString()
                                color: Theme.cText
                                font.family: Theme.font; font.pixelSize: Theme.smallSize
                                selectByMouse: true
                                validator: DoubleValidator { notation: DoubleValidator.StandardNotation }
                                onEditingFinished: app.setSection(bar.state.sectionPlane, Number(text))
                            }
                            Text { anchors.right: parent.right; anchors.rightMargin: 7; anchors.verticalCenter: parent.verticalCenter; text: "mm"; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11 }
                        }
                        ToolBtn { compact: true; text: "+"; onClicked: app.setSection(bar.state.sectionPlane, bar.state.sectionOffset + 5) }
                    }
                    Row {
                        spacing: 4
                        IconBtn { icon: "flip"; iconSize: 19; tint: Theme.cIcon; tip: qsTr("反向：换成看另一半"); active: bar.state.sectionFlip === true; onClicked: app.toggleViewSetting("sectionFlip") }
                        IconBtn { icon: "section"; iconSize: 19; tint: Theme.cIcon; tip: bar.state.section ? qsTr("关闭剖切") : qsTr("打开剖切"); active: bar.state.section; onClicked: app.toggleViewSetting("section") }
                    }
                    Text {
                        width: 210
                        wrapMode: Text.Wrap
                        text: qsTr("只是切开来看，不改零件；切口是敞开的（看得到内壁，没有封上的剖面）。")
                        color: Theme.cTextMuted
                        font.family: Theme.font; font.pixelSize: 11
                    }
                }
            }
        }
        Gap {}
        MenuBtn {
            icon: "cube"; tip: qsTr("视图定向：前、后、左、右、上、下、等轴测、正视于；新视图 = 记下现在的视角")
            items: app.orientations; itemWidth: 216
            onPicked: (id) => app.viewAction(id)
        }
        MenuBtn {
            icon: bar.state.style; tip: qsTr("显示样式：带边线上色、上色、消除隐藏线、隐藏线可见、线架图")
            items: app.displayStyles; current: bar.state.style
            onPicked: (id) => app.setDisplayStyle(id)
        }
        MenuBtn {
            icon: bar.state.hideAll ? "eye_off" : "eye"; tip: qsTr("隐藏/显示项目：基准面、基准轴、坐标系、点、原点、曲线、草图…")
            items: app.showItems; keepOpen: true
            onPicked: (id) => app.toggleShow(id)
        }
        Gap {}
        IconBtn {
            id: lookBtn
            icon: "appearance"; iconSize: 19
            tip: qsTr("编辑外观：给零件换个颜色")
            active: lookPop.opened
            onClicked: lookPop.opened ? lookPop.close() : lookPop.open()
            Popup {
                id: lookPop
                y: lookBtn.height + 9
                padding: 12
                background: Rectangle { color: Theme.cBgCard; radius: 9; border.width: 1; border.color: Theme.cDivider }
                contentItem: Column {
                    spacing: 10
                    Text { text: qsTr("编辑外观"); color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
                    Grid {
                        columns: 6; spacing: 6
                        Repeater {
                            model: app.appearanceColors
                            delegate: Rectangle {
                                required property string modelData
                                width: 26; height: 26; radius: 6
                                color: modelData
                                border.width: bar.state.color === modelData ? 2 : 1
                                border.color: bar.state.color === modelData ? Theme.cAccent : Theme.cDivider
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: app.setAppearance(parent.modelData) }
                            }
                        }
                    }
                    IconBtn { icon: "material"; iconSize: 19; tint: Theme.cIcon; tip: qsTr("跟随材质：不单独指定颜色，用材质的颜色（没指定材质就是默认的灰）"); active: bar.state.color === ""; onClicked: app.setAppearance("") }
                }
            }
        }
        MenuBtn {
            icon: "scene"; tip: qsTr("应用布景：换视图的背景")
            items: app.sceneNames; current: bar.state.scene
            onPicked: (id) => app.setScene(id)
        }
        MenuBtn {
            icon: "settings"; tip: qsTr("视图设定：透视图、卡通")
            keepOpen: true; itemWidth: 150
            items: [{ id: "perspective", title: qsTr("透视图"), checked: bar.state.perspective }, { id: "cartoon", title: qsTr("卡通"), checked: bar.state.cartoon }]
            onPicked: (id) => app.toggleViewSetting(id)
        }
    }
}
