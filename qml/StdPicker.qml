// StdPicker.qml - 插入标准件: 一个菜单一层一层选 (类别 → 系列 → 规格 → 长度), 选完 → sim.addStandardPart
import QtQuick

MenuList {
    id: picker
    property var catalog: sim.standardCatalog
    property var kind: null             // 选到的类别 (catalog 里的一项)
    property var series: null
    property string size: ""
    property string level: "kind"       // kind / series / size / length
    itemWidth: 250

    // 从头选: at = 菜单出现的位置 (相对 picker 的父件)
    function start(at) {
        level = "kind"; kind = null; series = null; size = ""
        show(catalog.map((row) => ({ id: row.id, title: row.title, icon: row.id === "screw" ? "screw" : "part" })), at)
    }
    function show(rows, at) {
        current = ""
        items = rows
        if (at) { x = at.x; y = at.y }
        open()
    }
    onPicked: (id) => {
        if (level === "kind") {
            kind = catalog.find((row) => row.id === id)
            if (kind.series.length > 1) {
                level = "series"
                Qt.callLater(show, kind.series.map((row) => ({ id: row.id, title: row.title, icon: "part" })))
                return
            }
            series = kind.series[0]
        } else if (level === "series") {
            series = kind.series.find((row) => row.id === id)
        } else if (level === "size") {
            size = id
            const lengths = kind.lengths ? kind.lengths[id] : null
            if (lengths && lengths.length) {
                level = "length"
                Qt.callLater(show, lengths.map((value) => ({ id: String(value), title: qsTr("长 %1 mm").arg(value), icon: "dimension" })))
                return
            }
            sim.addStandardPart(kind.id, series.id, size, "")
            return
        } else {
            sim.addStandardPart(kind.id, series.id, size, id)
            return
        }
        level = "size"
        Qt.callLater(show, series.sizes.map((row) => ({ id: row.id, title: row.title, icon: kind.id === "screw" ? "screw" : "part" })))
    }
}
