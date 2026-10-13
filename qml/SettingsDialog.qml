// SettingsDialog.qml - 设置: 快捷键 (每个功能一行, 点右边的键再按新的键) / 鼠标笔势 (右键手势轮的 8 格各放什么) / AI 接口 (怎么连)。
// 改了立刻生效, 存在用户目录里 (app.settingsPath), 和零件文件无关。
import QtQuick
import QtQuick.Controls

Popup {
    id: dialog
    parent: Overlay.overlay
    modal: true
    focus: true
    width: Math.min(860, parent ? parent.width - 60 : 860)
    height: Math.min(620, parent ? parent.height - 60 : 620)
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.round((parent.height - height) / 2) : 0
    padding: 0
    closePolicy: capturing !== "" ? Popup.NoAutoClose : Popup.CloseOnEscape
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }
    background: Rectangle { color: Theme.cBg; radius: 12; border.width: 1; border.color: Theme.cDivider }
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 130 }
        NumberAnimation { property: "scale"; from: 0.97; to: 1; duration: 160; easing.type: Easing.OutCubic }
    }

    property string page: "keys"        // keys / gestures / ai
    property string capturing: ""       // 正在等用户按键的那个功能的 id
    property string query: ""
    property string group: ""           // 只看哪一组 (空 = 全部)
    property var allRows: []            // 动作表 (打开时取一次: 列表不跟着每次改键重排)
    readonly property var rows: allRows.filter((row) => (group === "" || row.group === group) && matches(row, query))

    function matches(row, text) {
        if (text === "") return true
        const needle = text.toLowerCase()
        return row.title.toLowerCase().indexOf(needle) >= 0 || (app.keyMap[row.id] || "").toLowerCase().indexOf(needle) >= 0
    }
    onAboutToShow: { allRows = app.actionTable; capturing = "" }
    onClosed: capturing = ""

    component Field: Rectangle {        // 搜索框
        property alias text: input.text
        property string hint: ""
        function grab() { input.forceActiveFocus() }
        height: 30; radius: 6
        color: Theme.cBgInput
        border.width: 1; border.color: input.activeFocus ? Theme.cAccent : Theme.cDivider
        Icon { x: 8; anchors.verticalCenter: parent.verticalCenter; size: 15; name: "search"; color: Theme.cTextMuted }
        TextInput {
            id: input
            anchors.fill: parent; anchors.leftMargin: 30; anchors.rightMargin: 8
            verticalAlignment: TextInput.AlignVCenter
            color: Theme.cText
            font.family: Theme.font; font.pixelSize: Theme.textSize
            selectByMouse: true
            clip: true
        }
        Text {
            anchors.fill: input
            verticalAlignment: Text.AlignVCenter
            visible: input.text === ""
            text: parent.hint
            color: Theme.cTextMuted
            font.family: Theme.font; font.pixelSize: Theme.textSize
        }
    }
    component Heading: Text { color: Theme.cText; font.family: Theme.font; font.pixelSize: 15; font.bold: true }
    component Note: Text { color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize; wrapMode: Text.Wrap; lineHeight: 1.3 }

    contentItem: Item {
        // 等按键的时候, 键盘归这里
        Item {
            id: catcher
            focus: dialog.capturing !== ""
            Keys.onShortcutOverride: (event) => event.accepted = dialog.capturing !== ""
            Keys.onPressed: (event) => {
                if (dialog.capturing === "") return
                event.accepted = true
                if (event.key === Qt.Key_Escape) { dialog.capturing = ""; return }
                const text = app.keyText(event.key, event.modifiers)
                if (text === "") return                 // 只按了 Ctrl / Shift: 接着等
                app.setShortcut(dialog.capturing, text)
                dialog.capturing = ""
            }
        }

        // ---- 左边: 分页 ----
        Rectangle {
            id: side
            width: 172; height: parent.height
            color: Theme.cBgTitle
            radius: 12
            Rectangle { anchors.right: parent.right; width: 12; height: parent.height; color: parent.color }
            Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.cDivider }
            Column {
                x: 12; y: 16
                width: parent.width - 24
                spacing: 4
                Text { x: 6; height: 34; text: "设置"; color: Theme.cText; font.family: Theme.font; font.pixelSize: 16; font.bold: true }
                Repeater {
                    model: [{ id: "keys", text: "快捷键", icon: "keyboard" }, { id: "gestures", text: "鼠标笔势", icon: "gesture" },
                            { id: "ai", text: "AI 接口", icon: "ai" }]
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: dialog.page === modelData.id
                        width: parent.width; height: 34; radius: 7
                        color: on ? Theme.cAccentSoft : (pageArea.containsMouse ? Theme.cBgHover : "transparent")
                        border.width: on ? 1 : 0; border.color: Theme.cAccentLine
                        Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; size: 18; name: modelData.icon; color: parent.on ? Theme.cAccent : Theme.cIcon }
                        Text {
                            x: 38; anchors.verticalCenter: parent.verticalCenter
                            text: modelData.text
                            color: Theme.cText
                            font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: parent.on
                        }
                        MouseArea { id: pageArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { dialog.capturing = ""; dialog.page = modelData.id } }
                    }
                }
            }
        }
        IconBtn { anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 8; icon: "close"; tip: "关闭"; onClicked: dialog.close() }

        // ================= 快捷键 =================
        Item {
            visible: dialog.page === "keys"
            anchors.left: side.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
            anchors.margins: 20; anchors.topMargin: 18
            Heading { id: keysTitle; text: "快捷键" }
            Note { id: keysNote; anchors.top: keysTitle.bottom; anchors.topMargin: 4; width: parent.width - 40; text: "点右边的键，再按下新的键（可以带 Ctrl / Shift / Alt）。这个键原来给了别的功能的，那边自动让出来。Esc 和回车固定是取消和确认。" }
            Row {
                id: keysTools
                anchors.top: keysNote.bottom; anchors.topMargin: 12
                spacing: 6
                Field { width: 200; hint: "搜功能名或按键"; onTextChanged: dialog.query = text }
                Repeater {
                    model: [""].concat(app.actionGroups)
                    delegate: Rectangle {
                        required property string modelData
                        readonly property bool on: dialog.group === modelData
                        anchors.verticalCenter: parent.verticalCenter
                        width: chipText.implicitWidth + 22; height: 26; radius: 13
                        color: on ? Theme.cAccentStrong : (chipArea.containsMouse ? Theme.cBgHover : Theme.cBgWorkspace)
                        Text { id: chipText; anchors.centerIn: parent; text: modelData === "" ? "全部" : modelData; color: parent.on ? "#FFFFFF" : Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                        MouseArea { id: chipArea; anchors.fill: parent; hoverEnabled: true; onClicked: dialog.group = modelData }
                    }
                }
            }
            ToolBtn { anchors.right: parent.right; anchors.verticalCenter: keysTools.verticalCenter; compact: true; text: "全部恢复默认"; tip: "所有快捷键回到出厂的样子"; onClicked: { dialog.capturing = ""; app.resetShortcuts() } }
            Rectangle {
                anchors.top: keysTools.bottom; anchors.topMargin: 10
                anchors.bottom: parent.bottom
                width: parent.width
                radius: 8
                color: Theme.cBgWorkspace
                border.width: 1; border.color: Theme.cDivider
                ListView {
                    id: keyList
                    anchors.fill: parent; anchors.margins: 4
                    clip: true
                    model: dialog.rows
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: Rectangle {
                        id: keyRow
                        required property var modelData
                        readonly property string key: app.keyMap[modelData.id] || ""
                        readonly property bool waiting: dialog.capturing === modelData.id
                        width: keyList.width - 10; height: 34; radius: 6
                        color: waiting ? Theme.cAccentSoft : (rowHover.hovered ? Theme.cBgHover : "transparent")
                        HoverHandler { id: rowHover }
                        Icon { x: 10; anchors.verticalCenter: parent.verticalCenter; size: 18; name: keyRow.modelData.icon; color: Theme.cIcon }
                        Text {
                            x: 40; anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 40 - 250
                            elide: Text.ElideRight
                            text: keyRow.modelData.title
                            color: Theme.cText
                            font.family: Theme.font; font.pixelSize: Theme.textSize
                        }
                        Text {
                            anchors.right: keyBox.left; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
                            text: keyRow.modelData.group
                            color: Theme.cTextMuted
                            font.family: Theme.font; font.pixelSize: 11
                        }
                        Rectangle {             // 键: 点它开始等按键
                            id: keyBox
                            anchors.right: parent.right; anchors.rightMargin: 64; anchors.verticalCenter: parent.verticalCenter
                            width: 132; height: 26; radius: 6
                            color: keyRow.waiting ? Theme.cBgInput : (keyArea.containsMouse ? Theme.cBgCard : Theme.cBgInput)
                            border.width: 1; border.color: keyRow.waiting ? Theme.cAccent : (keyRow.key !== keyRow.modelData.default ? Theme.cAccentLine : Theme.cDivider)
                            Text {
                                anchors.centerIn: parent
                                text: keyRow.waiting ? "按下新的键…" : (keyRow.key !== "" ? keyRow.key : "无")
                                color: keyRow.waiting ? Theme.cAccent : (keyRow.key !== "" ? Theme.cText : Theme.cTextMuted)
                                font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: keyRow.key !== "" && !keyRow.waiting
                            }
                            MouseArea {
                                id: keyArea
                                anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                onClicked: { dialog.capturing = keyRow.waiting ? "" : keyRow.modelData.id; if (dialog.capturing !== "") catcher.forceActiveFocus() }
                            }
                        }
                        IconBtn {
                            anchors.right: parent.right; anchors.rightMargin: 32; anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: 26; implicitHeight: 26; iconSize: 15
                            visible: keyRow.key !== ""
                            icon: "cancel"; tip: "不要快捷键"
                            onClicked: { dialog.capturing = ""; app.setShortcut(keyRow.modelData.id, "") }
                        }
                        IconBtn {
                            anchors.right: parent.right; anchors.rightMargin: 4; anchors.verticalCenter: parent.verticalCenter
                            implicitWidth: 26; implicitHeight: 26; iconSize: 15
                            visible: keyRow.key !== keyRow.modelData.default
                            icon: "reset"; tip: "恢复默认：" + (keyRow.modelData.default !== "" ? keyRow.modelData.default : "无")
                            onClicked: { dialog.capturing = ""; app.resetShortcut(keyRow.modelData.id) }
                        }
                    }
                }
                Text {
                    anchors.centerIn: parent
                    visible: dialog.rows.length === 0
                    text: "没有找到"
                    color: Theme.cTextMuted
                    font.family: Theme.font; font.pixelSize: Theme.textSize
                }
            }
        }

        // ================= 鼠标笔势 =================
        Item {
            id: gesturePage
            visible: dialog.page === "gestures"
            anchors.left: side.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
            anchors.margins: 20; anchors.topMargin: 18
            Heading { id: wheelTitle; text: "鼠标笔势" }
            Note { id: wheelNote; anchors.top: wheelTitle.bottom; anchors.topMargin: 4; width: parent.width - 40; text: "在视图里按住右键朝一个方向一划，就执行那个方向上的功能。建模时和画草图时各一套，点一格换成别的功能。" }
            ToolBtn { anchors.right: parent.right; anchors.top: wheelNote.bottom; anchors.topMargin: 6; compact: true; text: "恢复默认"; tip: "两套手势轮都回到出厂的样子"; onClicked: app.resetGestures() }
            Row {
                anchors.top: wheelNote.bottom; anchors.topMargin: 34
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: Math.max(8, (gesturePage.width - 2 * 300) / 3)
                Repeater {
                    model: [{ id: "model", text: "建模时" }, { id: "sketch", text: "画草图时" }]
                    delegate: Item {
                        id: wheel
                        required property var modelData
                        readonly property var cells: app.gestureWheels[modelData.id] || []
                        width: 300; height: 330
                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter; y: 20
                            width: 290; height: 290; radius: 145
                            color: Theme.cBgWorkspace
                            border.width: 1; border.color: Theme.cDivider
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter; y: 20 + 145 - height / 2
                            text: wheel.modelData.text
                            color: Theme.cTextSec
                            font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true
                        }
                        Repeater {
                            model: wheel.cells
                            delegate: Rectangle {
                                id: cell
                                required property var modelData
                                required property int index
                                readonly property real angle: index * Math.PI / 4
                                x: 150 + Math.cos(angle) * 104 - width / 2
                                y: 165 - Math.sin(angle) * 104 - height / 2
                                width: 70; height: 56; radius: 10
                                color: cellArea.containsMouse ? Theme.cAccentSoft : Theme.cBgCard
                                border.width: 1; border.color: cellArea.containsMouse ? Theme.cAccent : Theme.cDivider
                                Icon { anchors.horizontalCenter: parent.horizontalCenter; y: 7; size: 22; name: cell.modelData.icon; color: Theme.cIcon }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter; y: 33
                                    width: parent.width - 6
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                    text: cell.modelData.text
                                    color: Theme.cText
                                    font.family: Theme.font; font.pixelSize: 11
                                }
                                MouseArea {
                                    id: cellArea
                                    anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: picker.openFor(wheel.modelData.id, cell.index, cell)
                                }
                                Tip { shown: cellArea.containsMouse && !picker.opened; text: cell.modelData.title + "：点一下换成别的功能" }
                            }
                        }
                    }
                }
            }
        }

        // 给手势轮的一格选功能
        Popup {
            id: picker
            property string which: ""
            property int slot: -1
            property string query: ""
            readonly property var rows: dialog.allRows.filter((row) => query === "" || row.title.toLowerCase().indexOf(query.toLowerCase()) >= 0)
            function openFor(which, slot, item) {
                picker.which = which; picker.slot = slot
                const at = item.mapToItem(dialog.contentItem, 0, 0)
                x = Math.max(8, Math.min(dialog.width - width - 8, at.x + item.width / 2 - width / 2))
                y = Math.max(8, Math.min(dialog.height - height - 8, at.y + item.height + 6))
                open()
            }
            width: 280; height: 360
            padding: 8
            focus: true
            background: Rectangle { color: Theme.cBgCard; radius: 10; border.width: 1; border.color: Theme.cAccentLine }
            onOpened: { pickField.text = ""; pickField.grab() }
            contentItem: Item {
                Field { id: pickField; width: parent.width; hint: "搜功能名"; onTextChanged: picker.query = text }
                ListView {
                    id: pickList
                    anchors.top: pickField.bottom; anchors.topMargin: 6; anchors.bottom: parent.bottom
                    width: parent.width
                    clip: true
                    model: picker.rows
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: Rectangle {
                        id: pickRow
                        required property var modelData
                        width: pickList.width - 10; height: 30; radius: 6
                        color: pickArea.containsMouse ? Theme.cBgHover : "transparent"
                        Icon { x: 8; anchors.verticalCenter: parent.verticalCenter; size: 18; name: pickRow.modelData.icon; color: pickArea.containsMouse ? Theme.cAccent : Theme.cIcon }
                        Text {
                            x: 34; anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 34 - 44
                            elide: Text.ElideRight
                            text: pickRow.modelData.title
                            color: Theme.cText
                            font.family: Theme.font; font.pixelSize: Theme.textSize
                        }
                        Text {
                            anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter
                            text: pickRow.modelData.group
                            color: Theme.cTextMuted
                            font.family: Theme.font; font.pixelSize: 11
                        }
                        MouseArea {
                            id: pickArea
                            anchors.fill: parent; hoverEnabled: true
                            onClicked: { app.setGesture(picker.which, picker.slot, pickRow.modelData.id); picker.close() }
                        }
                    }
                }
            }
        }

        // ================= AI 接口 =================
        Flickable {
            visible: dialog.page === "ai"
            anchors.left: side.right; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
            anchors.margins: 20; anchors.topMargin: 18
            contentHeight: aiColumn.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            component Snippet: Rectangle {      // 一段可以选中、可以一键复制的文字
                property alias text: code.text
                width: parent ? parent.width - 14 : 300
                height: code.implicitHeight + 20
                radius: 8
                color: Theme.cBgInput
                border.width: 1; border.color: Theme.cDivider
                TextEdit {
                    id: code
                    x: 12; y: 10
                    width: parent.width - 60
                    readOnly: true; selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    color: Theme.cText
                    selectionColor: Theme.cAccentStrong
                    font.family: "Consolas"; font.pixelSize: 12
                }
                IconBtn {
                    anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 4
                    icon: "copy"; tip: "复制"
                    onClicked: { code.selectAll(); code.copy(); code.deselect(); app.notice("已复制") }
                }
            }
            Column {
                id: aiColumn
                width: parent.width
                spacing: 10
                Heading { text: "AI 接口" }
                Note { width: parent.width - 40; text: "界面上能做的事，AI 都能通过这个接口做：画草图、拉伸、打孔、改参数、撤销、看图、导出。AI 画的时候你在窗口里看得见，也可以随时接手。接口只在本机开放（127.0.0.1），不联网。" }
                Row {
                    spacing: 8
                    Rectangle { anchors.verticalCenter: parent.verticalCenter; width: 8; height: 8; radius: 4; color: app.aiGuide.port > 0 ? "#3FB97F" : Theme.cError }
                    Text { text: apiText; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize }
                }
                Text { topPadding: 6; text: "① 接到 Claude Code（一条命令）"; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
                Snippet { text: app.aiGuide.claude }
                Text { topPadding: 6; text: "② 接到别的支持 MCP 的 AI 工具（写进它的 MCP 配置）"; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
                Snippet { text: app.aiGuide.mcp }
                Text { topPadding: 6; text: "③ 自己写程序连（每行一条 JSON）"; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
                Snippet { text: app.aiGuide.raw }
                Note { width: parent.width - 40; text: "接好以后直接用自然语言说要画什么就行。完整的上手说明、命令清单和例子在：" }
                Snippet { text: app.aiGuide.doc }
            }
        }
    }
}
