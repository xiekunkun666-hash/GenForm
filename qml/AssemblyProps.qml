// AssemblyProps.qml - 装配体的属性管理器: 选中了零部件 = 它的文件、类别、位置 / 转角、镜像, 打开零件; 没选 = 装配体概况和检查结果。
import QtQuick
import QtQuick.Controls

Flickable {
    id: page
    clip: true
    contentHeight: column.implicitHeight + 12
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    readonly property var parts: sim.components
    readonly property var part: sim.picked >= 0 && sim.picked < parts.length ? parts[sim.picked] : null
    // 运动副: 设计树上点的那个, 或者选中的零部件跟着动的那个
    readonly property int jointIndex: sim.pickedJoint >= 0 ? sim.pickedJoint : (part && part.joint >= 0 ? part.joint : -1)
    readonly property var joint: jointIndex >= 0 && jointIndex < sim.joints.length ? sim.joints[jointIndex] : null
    readonly property var state: sim.state

    component Num: TextField {
        id: num
        property string value: ""
        property string unit: ""
        signal commit(string text)
        width: 82; height: 26
        text: value
        selectByMouse: true
        color: Theme.cText
        font.family: Theme.font; font.pixelSize: Theme.textSize
        horizontalAlignment: TextInput.AlignRight
        leftPadding: 4; rightPadding: unit === "" ? 6 : 8 + unitText.implicitWidth
        topPadding: 0; bottomPadding: 0
        background: Rectangle { radius: 5; color: Theme.cBgInput; border.width: 1; border.color: num.activeFocus ? Theme.cAccent : Theme.cDivider }
        onActiveFocusChanged: if (activeFocus) selectAll()
        onEditingFinished: if (text !== value) commit(text)
        Keys.onEscapePressed: { text = value; focus = false }
        Text { id: unitText; anchors.right: parent.right; anchors.rightMargin: 5; anchors.verticalCenter: parent.verticalCenter; text: num.unit; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize }
    }
    component Btn: Rectangle {
        id: btn
        property string icon: ""
        property string text: ""
        property bool primary: false
        property bool danger: false
        signal clicked()
        height: 30; radius: 6
        color: primary ? (area.containsMouse ? Theme.cAccent : Theme.cAccentStrong) : (area.containsMouse ? Theme.cBgHover : Theme.cBgInput)
        border.width: primary ? 0 : 1; border.color: Theme.cDivider
        Row {
            anchors.centerIn: parent; spacing: 6
            Icon { anchors.verticalCenter: parent.verticalCenter; size: 15; name: btn.icon; color: btn.primary ? "#FFFFFF" : (btn.danger ? Theme.cError : Theme.cTextSec) }
            Text { anchors.verticalCenter: parent.verticalCenter; text: btn.text; color: btn.primary ? "#FFFFFF" : (btn.danger ? Theme.cError : Theme.cText); font.family: Theme.font; font.pixelSize: Theme.smallSize }
        }
        MouseArea { id: area; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: btn.clicked() }
    }
    component Line: Item {
        property string label: ""
        property string value: ""
        width: column.width; height: 22
        visible: value !== ""
        Text { anchors.verticalCenter: parent.verticalCenter; text: parent.label; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
        Text { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 80; horizontalAlignment: Text.AlignRight; elide: Text.ElideMiddle
               text: parent.value; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.smallSize }
    }

    Column {
        id: column
        x: 2; width: page.width - 10
        spacing: 8

        // ---- 运动副: 名字、类型、轴、装在哪、跟着动的件、范围 / 转速、滑块 ----
        MenuList { id: jointMenu; property string field: ""; itemWidth: 220; onPicked: (id) => sim.setJointField(page.jointIndex, field, id) }
        Column {
            visible: page.joint !== null
            width: parent.width; spacing: 6
            readonly property string kindNow: page.joint ? (page.joint.spin ? "spin" : page.joint.kind) : ""
            Row {
                spacing: 8
                Icon { anchors.verticalCenter: parent.verticalCenter; size: 18; name: page.joint && page.joint.kind === "slide" ? "move" : "hinge"; color: Theme.cAccent }
                Num {
                    width: column.width - 30; horizontalAlignment: TextInput.AlignLeft
                    value: page.joint ? page.joint.name : ""
                    onCommit: (text) => sim.setJointField(page.jointIndex, "name", text)
                }
            }
            Row {                           // 类型: 铰链 (来回转) / 滑动 / 一直转 (电机、齿轮)
                width: parent.width; spacing: 6
                Repeater {
                    model: [{ id: "hinge", title: qsTr("铰链"), icon: "hinge" }, { id: "slide", title: qsTr("滑动"), icon: "move" }, { id: "spin", title: qsTr("一直转"), icon: "motion" }]
                    delegate: Btn {
                        required property var modelData
                        width: (column.width - 12) / 3; icon: modelData.icon; text: modelData.title
                        primary: parent.parent.kindNow === modelData.id
                        onClicked: sim.setJointField(page.jointIndex, "kind", modelData.id)
                    }
                }
            }
            Item {                          // 轴的方向
                width: column.width; height: 28
                Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("轴的方向"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                Row {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                    Repeater {
                        model: ["X", "Y", "Z"]
                        delegate: Btn {
                            required property string modelData
                            required property int index
                            width: 40; height: 26; text: modelData
                            primary: page.joint !== null && Math.abs(page.joint.axis[index]) > 0.99
                            onClicked: sim.setJointField(page.jointIndex, "axis", modelData)
                        }
                    }
                }
            }
            Item {                          // 轴上一点
                width: column.width; height: 28
                Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("轴过"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                Row {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                    Repeater {
                        model: 3
                        delegate: Row {
                            required property int index
                            spacing: 3
                            Text { anchors.verticalCenter: parent.verticalCenter; text: "XYZ"[index]; color: [Theme.cAxisX, Theme.cAxisY, Theme.cAxisZ][index]; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
                            Num {
                                width: (column.width - 44) / 3 - 13
                                value: page.joint ? String(Math.round(page.joint.origin[index] * 1000) / 1000) : ""
                                onCommit: (text) => sim.setJointField(page.jointIndex, "origin" + index, text)
                            }
                        }
                    }
                }
            }
            Btn {
                width: parent.width; icon: "zoom_sel"; enabled: sim.picked >= 0
                text: qsTr("轴挪到选中零部件的中心")
                onClicked: sim.jointCentre(page.jointIndex)
            }
            Item {                          // 装在哪个件上
                width: column.width; height: 28
                Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("装在"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                Btn {
                    id: baseBtn
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    width: column.width - 80; height: 26; icon: "part"
                    text: page.joint ? page.joint.base : ""
                    onClicked: {
                        jointMenu.field = "base"
                        jointMenu.items = page.parts.map((row) => ({ id: String(row.index), title: row.label, icon: "part" }))
                        jointMenu.current = page.joint ? String(page.joint.baseIndex) : ""
                        const at = baseBtn.mapToItem(column, 0, baseBtn.height + 2)
                        jointMenu.x = at.x; jointMenu.y = at.y; jointMenu.open()
                    }
                }
            }
            Item {                          // 一直转的: 跟着哪个运动副一起转 (行星轮跟着行星架)
                visible: parent.kindNow === "spin"
                width: column.width; height: 28
                Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("跟着转"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                Btn {
                    id: onBtn
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    width: column.width - 80; height: 26; icon: "hinge"
                    text: page.joint && page.joint.onName !== "" ? page.joint.onName : qsTr("不跟（绕固定的轴转）")
                    onClicked: {
                        jointMenu.field = "on"
                        jointMenu.items = [{ id: "-1", title: qsTr("不跟（绕固定的轴转）"), icon: "close" }]
                            .concat(sim.joints.filter((row) => row.index !== page.jointIndex)
                                    .map((row) => ({ id: String(row.index), title: row.name, icon: "hinge" })))
                        jointMenu.current = page.joint ? String(page.joint.on) : ""
                        const at = onBtn.mapToItem(column, 0, onBtn.height + 2)
                        jointMenu.x = at.x; jointMenu.y = at.y; jointMenu.open()
                    }
                }
            }
            Item {                          // 一直转: 转速
                visible: parent.kindNow === "spin"
                width: column.width; height: 28
                Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("转速（负数反转）"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                Num {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    width: 110; unit: "°/s"
                    value: page.joint ? String(page.joint.speed) : ""
                    onCommit: (text) => sim.setJointField(page.jointIndex, "speed", text)
                }
            }
            Item {                          // 铰链 / 滑动: 能动的范围
                visible: parent.kindNow !== "spin"
                width: column.width; height: 28
                Text { anchors.verticalCenter: parent.verticalCenter; text: qsTr("范围"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                Row {
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                    Num { width: 90; unit: page.joint ? page.joint.unit : ""; value: page.joint ? String(page.joint.min) : ""; onCommit: (text) => sim.setJointField(page.jointIndex, "min", text) }
                    Text { anchors.verticalCenter: parent.verticalCenter; text: "~"; color: Theme.cTextSec }
                    Num { width: 90; unit: page.joint ? page.joint.unit : ""; value: page.joint ? String(page.joint.max) : ""; onCommit: (text) => sim.setJointField(page.jointIndex, "max", text) }
                }
            }
            Text { width: parent.width; wrapMode: Text.Wrap; visible: page.joint !== null
                   text: page.joint ? qsTr("跟着动：") + page.joint.parts.join("、") : ""
                   color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            Btn {
                width: parent.width; icon: "part"; primary: page.joint !== null && page.joint.adding
                text: page.joint && page.joint.adding ? qsTr("点选中：点零部件加进来 / 再点去掉（点这里结束）") : qsTr("点选跟着动的零部件")
                onClicked: sim.pickJointParts(page.jointIndex)
            }
            Text { visible: parent.kindNow === "spin"; width: parent.width; wrapMode: Text.Wrap
                   text: qsTr("点上面的“播放动画”，所有“一直转”的运动副按各自的转速一起转；齿轮传动按齿数比填转速（输出 = 输入 ÷ 减速比）")
                   color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11 }
            Item {
                visible: parent.kindNow !== "spin"
                width: parent.width; height: 26
                ValueSlider {
                    anchors.left: parent.left; anchors.right: valueText.left; anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    from: page.joint ? page.joint.min : 0; to: page.joint ? page.joint.max : 1; value: page.joint ? page.joint.value : 0
                    onMoved: (value) => sim.setJoint(page.jointIndex, value)
                    onReleased: sim.settleJoint()
                }
                Text {
                    id: valueText
                    anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                    width: 52; horizontalAlignment: Text.AlignRight
                    text: page.joint ? page.joint.value.toFixed(1) + " " + page.joint.unit : ""
                    color: Theme.cAccent; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true
                }
            }
            Row {
                visible: parent.kindNow !== "spin"
                width: parent.width; spacing: 6
                Btn { width: (parent.width - 12) / 3; icon: "down"; text: qsTr("关上"); onClicked: sim.jointAction(page.jointIndex, "close") }
                Btn { width: (parent.width - 12) / 3; icon: "hinge"; text: qsTr("一半"); onClicked: sim.jointAction(page.jointIndex, "half") }
                Btn { width: (parent.width - 12) / 3; primary: true; icon: "up"; text: qsTr("打开"); onClicked: sim.jointAction(page.jointIndex, "open") }
            }
            Text { visible: parent.kindNow !== "spin"; width: parent.width; wrapMode: Text.Wrap; text: qsTr("也可以在视图里按住它直接拖；松手以后实时检查按新的位置查干涉")
                   color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11 }
            Btn { width: parent.width; icon: "trash"; danger: true; text: qsTr("删除这个运动副"); onClicked: sim.deleteJoint(page.jointIndex) }
            Rectangle { width: parent.width; height: 1; color: Theme.cDivider; visible: page.part !== null }
        }

        // ---- 选中的零部件 ----
        Column {
            visible: page.part !== null
            width: parent.width; spacing: 6
            Row {
                spacing: 8
                Icon { anchors.verticalCenter: parent.verticalCenter; size: 18; name: page.part && page.part.mirror ? "mirror" : "part"; color: Theme.cAccent }
                Text { anchors.verticalCenter: parent.verticalCenter; text: page.part ? page.part.label : ""; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize + 1; font.bold: true }
                Text { anchors.verticalCenter: parent.verticalCenter; visible: page.part && page.part.fixed; text: qsTr("(固定)"); color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            }
            Line { label: qsTr("文件"); value: page.part ? page.part.file : "" }
            Line { label: qsTr("类别"); value: page.part ? page.part.kind : "" }
            Line { label: qsTr("规格"); value: page.part ? page.part.spec : "" }
            Line { label: qsTr("工艺"); value: page.part ? page.part.process : "" }
            Line { label: qsTr("材质"); value: page.part ? qsTr(page.part.material) : "" }
            Line { label: qsTr("每件估价"); value: page.part && page.part.unit > 0 ? "¥" + Math.round(page.part.unit).toLocaleString(Qt.locale(), 'f', 0) : "" }
            Rectangle { width: parent.width; height: 1; color: Theme.cDivider }
            Text { text: qsTr("位置（先镜像，再依次绕 X、Y、Z 转，再平移）"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            Repeater {
                model: [{ field: "move", title: qsTr("平移"), unit: "" }, { field: "turn", title: qsTr("转角"), unit: "°" }]
                delegate: Item {
                    id: placeRow
                    required property var modelData
                    width: column.width; height: 28
                    enabled: page.part !== null && page.part.file !== ""
                    Text { anchors.verticalCenter: parent.verticalCenter; text: placeRow.modelData.title; color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                        Repeater {
                            model: 3
                            delegate: Row {
                                required property int index
                                spacing: 3
                                Text { anchors.verticalCenter: parent.verticalCenter; text: "XYZ"[index]; color: [Theme.cAxisX, Theme.cAxisY, Theme.cAxisZ][index]; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
                                Num {
                                    width: (column.width - 44) / 3 - 13          // 三格加 XYZ 正好放下, 左边留给 "平移" 两个字
                                    readonly property string formula: page.part && page.part.formula ? page.part.formula[placeRow.modelData.field][index] : ""
                                    readonly property bool mated: page.part !== null && placeRow.modelData.field === "move" && page.part.mated.indexOf(index) >= 0
                                    value: formula !== "" && !activeFocus ? formula
                                           : (page.part ? String(Math.round(page.part[placeRow.modelData.field][index] * 1000) / 1000) : "")
                                    readOnly: mated
                                    color: mated ? Theme.cAccent : (formula !== "" ? Theme.cAccent : Theme.cText)
                                    unit: placeRow.modelData.unit
                                    Tip { shown: parent.hovered && (parent.formula !== "" || parent.mated)
                                          text: parent.mated ? qsTr("这个方向是配合定的") : qsTr("表达式 %1 = %2").arg(parent.formula).arg(page.part ? Math.round(page.part[placeRow.modelData.field][index] * 1000) / 1000 : "") }
                                    onCommit: (text) => sim.placePart(sim.picked, placeRow.modelData.field, index, text)
                                }
                            }
                        }
                    }
                }
            }
            Row {
                spacing: 8
                enabled: page.part !== null && page.part.file !== ""
                CheckBox {
                    id: mirrorBox
                    checked: page.part ? page.part.mirror : false
                    onToggled: sim.mirrorPart(sim.picked)
                    Tip { shown: mirrorBox.hovered; text: qsTr("对零件自己的 XZ 面镜像：左边的件变成右边那个相反方位的件") }
                    indicator: Rectangle {
                        implicitWidth: 16; implicitHeight: 16; radius: 4
                        x: mirrorBox.leftPadding; y: (mirrorBox.height - height) / 2
                        color: mirrorBox.checked ? Theme.cAccentStrong : Theme.cBgInput
                        border.width: 1; border.color: mirrorBox.checked ? Theme.cAccent : Theme.cDivider
                        Icon { anchors.centerIn: parent; size: 12; name: "check"; color: "#FFFFFF"; visible: mirrorBox.checked }
                    }
                    contentItem: Text { leftPadding: mirrorBox.indicator.width + 8; verticalAlignment: Text.AlignVCenter; text: qsTr("镜像（左右相反方位的件）"); elide: Text.ElideRight; width: column.width - 30; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                }
            }
            // ---- 配合: 这个零件摆在谁上面 (同轴 / 沿某根轴差多少) ----
            MenuList { id: mateMenu; property string kind: ""; itemWidth: 220; onPicked: (id) => sim.addMate(sim.picked, parseInt(id), kind, "Z") }
            Repeater {
                model: sim.mates.filter((row) => row.part === sim.picked)
                delegate: Item {
                    id: mateRow
                    required property var modelData
                    width: column.width; height: 28
                    Text { anchors.verticalCenter: parent.verticalCenter; width: parent.width - mateRight.width - 6; elide: Text.ElideRight
                           text: modelData.title + qsTr(" → ") + modelData.toName; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                    Row {
                        id: mateRight
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 3
                        Repeater {
                            model: ["X", "Y", "Z"]
                            delegate: Btn {
                                required property string modelData
                                width: 24; height: 24; text: modelData
                                primary: mateRow.modelData.axis === modelData
                                onClicked: sim.setMateField(mateRow.modelData.index, "axis", modelData)
                            }
                        }
                        Num {
                            visible: modelData.kind === "offset"
                            width: 70; height: 24; value: modelData.value
                            onCommit: (text) => sim.setMateField(modelData.index, "value", text)
                        }
                        Btn { width: 24; height: 24; icon: "trash"; danger: true; onClicked: sim.setMateField(modelData.index, "delete", "") }
                    }
                }
            }
            Row {
                width: parent.width; spacing: 6
                visible: page.part !== null && sim.picked > 0
                Repeater {
                    model: [{ kind: "coaxial", title: qsTr("同轴于…"), icon: "axis" }, { kind: "offset", title: qsTr("距离…"), icon: "dimension" }]
                    delegate: Btn {
                        id: mateBtn
                        required property var modelData
                        width: (column.width - 6) / 2; icon: modelData.icon; text: modelData.title
                        onClicked: {
                            mateMenu.kind = modelData.kind
                            mateMenu.items = page.parts.filter((row) => row.index !== sim.picked).map((row) => ({ id: String(row.index), title: row.label, icon: "part" }))
                            const at = mateBtn.mapToItem(column, 0, mateBtn.height + 2)
                            mateMenu.x = at.x; mateMenu.y = at.y; mateMenu.open()
                        }
                    }
                }
            }
            Btn {
                visible: page.part !== null && page.part.joint < 0
                width: parent.width; icon: "hinge"
                text: qsTr("给它加运动副（铰链 / 滑动 / 一直转）")
                onClicked: sim.addJoint(sim.picked)
            }
            Row {
                width: parent.width; spacing: 6
                Btn { width: (parent.width - 12) / 3; primary: true; icon: "open"; text: qsTr("打开零件"); onClicked: sim.openPart(sim.picked) }
                Btn { width: (parent.width - 12) / 3; icon: "eye"; text: page.part && page.part.hidden ? qsTr("显示") : qsTr("隐藏"); onClicked: sim.partAction(sim.picked, "hide") }
                Btn { width: (parent.width - 12) / 3; icon: "trash"; danger: true; text: qsTr("删除"); onClicked: sim.partAction(sim.picked, "delete") }
            }
        }

        // ---- 没选零部件: 装配体概况 + 检查结果 ----
        Column {
            visible: page.part === null && page.joint === null
            width: parent.width; spacing: 6
            Text { text: sim.assemblyName; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.textSize + 1; font.bold: true }
            Text { width: parent.width; wrapMode: Text.Wrap; text: qsTr("%1 个零部件。在设计树或视图里点一个零部件看它的属性、改位置").arg(page.parts.length); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            // ---- 全局变量: 改了写进零件文件里同名的变量, 位置里的 =表达式 和配合跟着变 ----
            Text { text: qsTr("全局变量"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
            Repeater {
                model: sim.params
                delegate: Item {
                    required property var modelData
                    width: column.width; height: 28
                    Text { anchors.verticalCenter: parent.verticalCenter; text: modelData.name; color: Theme.cText; font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: true }
                    Row {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                        Text { anchors.verticalCenter: parent.verticalCenter; visible: modelData.text.charAt(0) === "="; text: "= " + modelData.value; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                        Num { width: 110; value: modelData.text; onCommit: (text) => sim.setParam(modelData.name, text) }
                        Btn { width: 26; height: 26; icon: "trash"; danger: true; onClicked: sim.setParam(modelData.name, "") }
                    }
                }
            }
            Row {
                width: parent.width; spacing: 4
                Num { id: newName; width: 90; horizontalAlignment: TextInput.AlignLeft; placeholderText: qsTr("名字") }
                Num { id: newValue; width: parent.width - 90 - 70 - 8; placeholderText: qsTr("值 或 =表达式") }
                Btn {
                    width: 70; height: 26; icon: "plus"; text: qsTr("加")
                    onClicked: { if (newName.text !== "" && newValue.text !== "") { sim.setParam(newName.text, newValue.text); newName.text = ""; newValue.text = "" } }
                }
            }
            Text { visible: sim.paramError !== ""; width: parent.width; wrapMode: Text.Wrap; text: sim.paramError; color: Theme.cError; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            Text { width: parent.width; wrapMode: Text.Wrap; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11
                   text: qsTr("零件里加“全局变量”特征定义同名的变量，特征参数写 =表达式 引用；零件位置也能写 =表达式。") }
            Rectangle { width: parent.width; height: 1; color: Theme.cDivider }
            Row {
                width: parent.width; spacing: 6
                Btn { width: (parent.width - 12) / 3; primary: true; icon: "clash"; text: qsTr("干涉检查"); onClicked: sim.runInterference() }
                Btn { width: (parent.width - 12) / 3; icon: "order"; text: qsTr("装配顺序"); onClicked: sim.runSequence() }
                Btn { width: (parent.width - 12) / 3; icon: "drc"; text: qsTr("设计检查"); onClicked: app.runCheck() }
            }
            Row {
                width: parent.width; spacing: 6
                Btn { width: (parent.width - 12) / 3; icon: "thread"; text: qsTr("螺纹检查"); onClicked: sim.runFasteners() }
                Btn { width: (parent.width - 12) / 3; icon: "check"; text: qsTr("对齐螺纹"); onClicked: sim.alignThreads() }
                Btn { width: (parent.width - 12) / 3; icon: "dimension"; text: qsTr("尺寸链"); onClicked: sim.runStack("Z") }
            }
            Text { visible: page.state.running; text: qsTr("正在算…"); color: Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
            Text { visible: page.state.error !== ""; width: parent.width; wrapMode: Text.Wrap; text: page.state.error; color: Theme.cError; font.family: Theme.font; font.pixelSize: Theme.textSize; font.bold: true }
            Repeater {
                model: page.state.rows
                delegate: Item {
                    required property var modelData
                    width: column.width; height: 22
                    Text { anchors.verticalCenter: parent.verticalCenter; width: parent.width - value.width - 8; elide: Text.ElideRight; text: modelData.label; color: modelData.strong ? Theme.cText : Theme.cTextSec; font.family: Theme.font; font.pixelSize: Theme.smallSize }
                    Text { id: value; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; text: modelData.value; color: modelData.bad ? Theme.cError : (modelData.strong ? Theme.cAccent : Theme.cText); font.family: Theme.font; font.pixelSize: Theme.smallSize; font.bold: modelData.strong }
                }
            }
            Repeater {
                model: page.state.notes
                delegate: Text { required property string modelData; width: column.width; wrapMode: Text.Wrap; text: modelData; color: Theme.cTextMuted; font.family: Theme.font; font.pixelSize: 11 }
            }
        }
    }
}
