// FormPanel.qml - 参数面板: 新建或编辑一个特征时填参数。回车确定, Esc 取消。
// 是浮在三维视图上的一张卡片 (高度随内容): 它出现和消失都不挤视图, 画面不会跟着跳
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: panel
    property var form: app.form
    color: Qt.rgba(Theme.cBg.r, Theme.cBg.g, Theme.cBg.b, 0.96)
    radius: 10
    border.width: 1
    border.color: Theme.cDivider
    visible: form !== null && form !== undefined
    height: content.implicitHeight + 28

    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: (wheel) => wheel.accepted = true }   // 卡片上的点击和滚轮不漏到下面的视图

    // 把还没提交的输入框内容都写回去 (点 "确定" 时光标可能还在某个输入框里)
    function commitAll() {
        for (let i = 0; i < fields.count; ++i) {
            const item = fields.itemAt(i)
            if (item && item.commit) item.commit()
        }
    }
    function accept() { commitAll(); app.acceptForm() }
    function enter(row) { if (app.sketchActive) row.commit(); else accept() }
    function trim(value) { return String(Math.round(value * 10000) / 10000) }

    ColumnLayout {
        id: content
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 14
        spacing: 10

        Text {
            text: panel.form ? panel.form.title : ""
            color: Theme.cText
            font.family: Theme.font; font.pixelSize: 15; font.bold: true
        }

        Repeater {
            id: fields
            model: panel.form ? panel.form.fields : []
            delegate: Loader {
                id: slot
                required property var modelData
                Layout.fillWidth: true
                visible: modelData.hidden !== true          // 拉伸: 终止条件用不上的那几项收起来
                function commit() { if (item && item.commit) item.commit() }
                sourceComponent: modelData.type === "number" ? numberField
                               : modelData.type === "choice" ? choiceField
                               : modelData.type === "bool" ? boolField
                               : modelData.type === "text" ? textField
                               : modelData.type === "multi" ? multiField : infoField
                onLoaded: item.field = modelData
            }
        }

        Text {                              // 预览算不出来的原因
            Layout.fillWidth: true
            visible: text !== "" && !app.sketchActive
            text: app.previewNote
            wrapMode: Text.Wrap
            color: Theme.cError
            font.family: Theme.font; font.pixelSize: Theme.smallSize
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 2
            visible: panel.form ? panel.form.accept !== "" : false
            spacing: 8
            Item { Layout.fillWidth: true }
            IconBtn { visible: tip !== ""; icon: "cancel"; iconSize: 20; tint: Theme.cText; tip: panel.form ? panel.form.cancel : ""; onClicked: app.cancelForm() }
            IconBtn { visible: tip !== ""; icon: "finish"; iconSize: 20; tint: Theme.cAccent; active: true; tip: panel.form ? panel.form.accept : ""; onClicked: panel.accept() }
        }
    }

    Component {
        id: numberField
        RowLayout {
            property var field
            spacing: 8
            function commit() {
                const value = Number(input.text.replace(",", "."))
                if (field && isFinite(value) && input.text.trim() !== "") app.setField(field.key, value)
            }
            Text {
                text: field ? field.label : ""
                color: Theme.cTextSec
                font.family: Theme.font; font.pixelSize: Theme.textSize
                Layout.preferredWidth: 96
                elide: Text.ElideRight
            }
            TextField {
                id: input
                Layout.fillWidth: true
                text: field ? panel.trim(field.value) : ""
                selectByMouse: true
                color: Theme.cText
                font.family: Theme.font; font.pixelSize: Theme.textSize
                horizontalAlignment: TextInput.AlignRight
                rightPadding: 34
                background: Rectangle {
                    radius: 5
                    color: Theme.cBgInput
                    border.width: 1
                    border.color: input.activeFocus ? Theme.cAccent : Theme.cDivider
                }
                onActiveFocusChanged: if (activeFocus) selectAll()
                onEditingFinished: parent.commit()
                onTextEdited: if (!app.sketchActive) parent.commit()     // 特征的面板: 边打字视图里的预览边跟着变
                // 回车: 普通面板 = 确定; 草图里只是把这个尺寸填进去 (完成草图要点按钮, 免得填个数就退出了)
                Keys.onReturnPressed: panel.enter(parent)
                Keys.onEnterPressed: panel.enter(parent)
                Keys.onEscapePressed: app.escape()
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: field ? (field.unit || "") : ""
                    color: Theme.cTextMuted
                    font.family: Theme.font; font.pixelSize: Theme.smallSize
                }
            }
        }
    }

    Component {
        id: textField
        RowLayout {
            property var field
            spacing: 8
            function commit() { if (field) app.setField(field.key, entry.text) }
            Text {
                text: field ? field.label : ""
                color: Theme.cTextSec
                font.family: Theme.font; font.pixelSize: Theme.textSize
                Layout.preferredWidth: 96
            }
            TextField {
                id: entry
                Layout.fillWidth: true
                text: field ? field.value : ""
                selectByMouse: true
                color: Theme.cText
                font.family: Theme.font; font.pixelSize: Theme.textSize
                background: Rectangle {
                    radius: 5
                    color: Theme.cBgInput
                    border.width: 1
                    border.color: entry.activeFocus ? Theme.cAccent : Theme.cDivider
                }
                onTextEdited: parent.commit()           // 边打字视图里的字边跟着变
                Keys.onEscapePressed: app.escape()
            }
        }
    }

    Component {
        id: choiceField
        RowLayout {
            id: choiceRow
            property var field
            spacing: 8
            Text {                          // 点这一项的名字: 接下来在视图里点的东西填这一项 (有两根轴要选时用)
                readonly property bool active: panel.form && choiceRow.field && panel.form.active === choiceRow.field.key
                text: field ? field.label : ""
                color: active ? Theme.cAccent : Theme.cTextSec
                font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: active
                Layout.preferredWidth: 96
                MouseArea { anchors.fill: parent; onClicked: if (choiceRow.field) app.focusField(choiceRow.field.key) }
            }
            Flow {
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: choiceRow.field ? choiceRow.field.options : []
                    delegate: Rectangle {
                        required property var modelData
                        property bool on: choiceRow.current === modelData.value
                        width: optionText.implicitWidth + 18; height: 28; radius: 5
                        color: on ? Theme.cAccentSoft : (optionArea.containsMouse ? Theme.cBgHover : Theme.cBgInput)
                        border.width: 1
                        border.color: on ? Theme.cAccent : Theme.cDivider
                        Text {
                            id: optionText
                            anchors.centerIn: parent
                            text: modelData.label
                            color: on ? Theme.cAccent : Theme.cText
                            font.family: Theme.font; font.pixelSize: Theme.smallSize
                        }
                        MouseArea {
                            id: optionArea
                            anchors.fill: parent; hoverEnabled: true
                            onClicked: { choiceRow.current = modelData.value; app.setField(choiceRow.field.key, modelData.value) }
                        }
                    }
                }
            }
            property var current: field ? field.value : undefined
            onFieldChanged: current = field ? field.value : undefined
        }
    }

    Component {
        id: multiField          // 多选: 点一下选上, 再点一下去掉; 顺序就是点的顺序 (放样的轮廓顺序)
        ColumnLayout {
            id: multiRow
            property var field
            property var chosen: []
            onFieldChanged: chosen = field ? field.value.slice() : []
            spacing: 4
            Text {
                text: field ? field.label + (multiRow.chosen.length ? qsTr("（已选 %1）").arg(multiRow.chosen.length) : "") : ""
                color: Theme.cTextSec
                font.family: Theme.font; font.pixelSize: Theme.textSize
            }
            Flow {
                Layout.fillWidth: true
                spacing: 4
                Repeater {
                    model: multiRow.field ? multiRow.field.options : []
                    delegate: Rectangle {
                        required property var modelData
                        readonly property int order: multiRow.chosen.indexOf(modelData.value)
                        width: chipText.implicitWidth + 18; height: 28; radius: 5
                        color: order >= 0 ? Theme.cAccentSoft : (chipArea.containsMouse ? Theme.cBgHover : Theme.cBgInput)
                        border.width: 1
                        border.color: order >= 0 ? Theme.cAccent : Theme.cDivider
                        Text {
                            id: chipText
                            anchors.centerIn: parent
                            text: (parent.order >= 0 ? (parent.order + 1) + " " : "") + modelData.label
                            color: parent.order >= 0 ? Theme.cAccent : Theme.cText
                            font.family: Theme.font; font.pixelSize: Theme.smallSize
                        }
                        MouseArea {
                            id: chipArea
                            anchors.fill: parent; hoverEnabled: true
                            onClicked: {
                                const next = multiRow.chosen.slice()
                                if (parent.order >= 0) next.splice(parent.order, 1); else next.push(modelData.value)
                                multiRow.chosen = next
                                app.setField(multiRow.field.key, next)
                            }
                        }
                    }
                }
                Text {
                    visible: multiRow.field ? multiRow.field.options.length === 0 : false
                    text: qsTr("（还没有可选的）")
                    color: Theme.cTextMuted
                    font.family: Theme.font; font.pixelSize: Theme.smallSize
                }
            }
        }
    }

    Component {
        id: boolField
        RowLayout {
            id: boolRow
            property var field
            property bool on: false
            onFieldChanged: on = field ? field.value : false
            spacing: 8
            Rectangle {
                width: 18; height: 18; radius: 4
                color: boolRow.on ? Theme.cAccent : Theme.cBgInput
                border.width: 1
                border.color: boolRow.on ? Theme.cAccent : Theme.cDivider
                Text { anchors.centerIn: parent; text: "✓"; color: "#FFFFFF"; visible: boolRow.on; font.pixelSize: 12 }
                MouseArea {
                    anchors.fill: parent; anchors.margins: -4
                    onClicked: { boolRow.on = !boolRow.on; app.setField(boolRow.field.key, boolRow.on) }
                }
            }
            Text {
                text: field ? field.label : ""
                color: Theme.cText
                font.family: Theme.font; font.pixelSize: Theme.textSize
                Layout.fillWidth: true
            }
        }
    }

    Component {
        id: infoField
        Text {
            property var field
            text: field ? field.value : ""
            wrapMode: Text.Wrap
            color: Theme.cTextSec
            font.family: Theme.font; font.pixelSize: Theme.smallSize
        }
    }
}
