// Icon.qml - 线条图标 (自己画, 不依赖图标字体)。name 选图案, color 是线的颜色
import QtQuick

Canvas {
    id: icon
    property string name: ""
    property color color: Theme.cText
    property real size: 22
    width: size
    height: size
    antialiasing: true
    onNameChanged: requestPaint()
    onColorChanged: requestPaint()

    onPaint: {
        const c = getContext("2d")
        c.reset()
        c.scale(width / 24, height / 24)
        c.strokeStyle = icon.color
        c.fillStyle = icon.color
        c.lineWidth = 1.7
        c.lineCap = "round"
        c.lineJoin = "round"
        function line() { c.beginPath(); c.moveTo(arguments[0], arguments[1]); for (let i = 2; i < arguments.length; i += 2) c.lineTo(arguments[i], arguments[i + 1]); c.stroke() }
        function closed() { c.beginPath(); c.moveTo(arguments[0], arguments[1]); for (let i = 2; i < arguments.length; i += 2) c.lineTo(arguments[i], arguments[i + 1]); c.closePath(); c.stroke() }
        function dot(x, y) { c.beginPath(); c.arc(x, y, 1.7, 0, Math.PI * 2); c.fill() }

        function ring(x, y, r) { c.beginPath(); c.arc(x, y, r, 0, Math.PI * 2); c.stroke() }
        function fill(alpha) { c.globalAlpha = alpha; c.beginPath(); c.moveTo(arguments[1], arguments[2]); for (let i = 3; i < arguments.length; i += 2) c.lineTo(arguments[i], arguments[i + 1]); c.closePath(); c.fill(); c.globalAlpha = 1 }
        // 一个斜着看的方盒子 (显示样式、视图方向这些图标都用它): 前面的方框 + 往右上退的后框
        function box(hidden) {
            closed(4, 9, 15, 9, 15, 20, 4, 20); line(4, 9, 9, 4, 20, 4, 15, 9); line(20, 4, 20, 15, 15, 20)
            if (hidden > 0) { c.globalAlpha = hidden; c.lineWidth = 1.1; line(9, 4, 9, 15, 20, 15); line(9, 15, 4, 20); c.globalAlpha = 1; c.lineWidth = 1.7 }
        }
        function eye() { c.beginPath(); c.moveTo(2, 12); c.quadraticCurveTo(12, 2.5, 22, 12); c.quadraticCurveTo(12, 21.5, 2, 12); c.stroke(); ring(12, 12, 3) }
        function arcSlot() { c.beginPath(); c.arc(12, 19, 11, Math.PI * 1.15, Math.PI * 1.85); c.arc(12, 19, 6, Math.PI * 1.85, Math.PI * 1.15, true); c.closePath(); c.stroke() }
        function around() { for (let k = 0; k < 6; k++) ring(12 + 8 * Math.cos(k * Math.PI / 3), 12 + 8 * Math.sin(k * Math.PI / 3), 2.1) }
        const alias = ({ "pattern_linear": "pattern", "pattern_circular": "cpattern", "csys": "origin", "curve_helix": "curve",
                         "orient": "cube", "iso": "cube", "style": "shaded_edges",
                         "show_main_planes": "plane", "show_planes": "reference", "show_axes": "axis", "show_csys": "origin",
                         "show_points": "point", "show_origin": "origin", "show_curves": "curve", "show_sketches": "sketch",
                         "show_sketch3d": "sketch3d", "show_com": "com", "show_bbox": "bbox" })

        switch (alias[icon.name] || icon.name) {
        // ---- 草图工具 ----
        case "centerline":
            line(4, 20, 8, 16); line(10.5, 13.5, 13.5, 10.5); line(16, 8, 20, 4); break
        case "midline":
            line(4, 19, 20, 5); dot(12, 12); break
        case "crect":
            closed(4, 6, 20, 6, 20, 18, 4, 18); dot(12, 12); break
        case "rect3":
            closed(5, 10, 14, 4, 20, 13, 11, 19); dot(5, 10); dot(14, 4); dot(20, 13); break
        case "crect3":
            closed(5, 10, 14, 4, 20, 13, 11, 19); dot(12.5, 11.5); dot(17, 8.5); break
        case "pgram":
            closed(3, 18, 8, 6, 21, 6, 16, 18); break
        case "cslot":
            c.beginPath(); c.moveTo(8, 8); c.lineTo(16, 8); c.arc(16, 12, 4, -Math.PI / 2, Math.PI / 2); c.lineTo(8, 16); c.arc(8, 12, 4, Math.PI / 2, Math.PI * 1.5); c.stroke(); dot(12, 12); break
        case "aslot3":
            arcSlot(); dot(4.5, 13.5); dot(12, 10.5); dot(19.5, 13.5); break
        case "caslot":
            arcSlot(); dot(12, 19); break
        case "circle3":
            ring(12, 12, 8); dot(12, 4); dot(5.1, 16); dot(18.9, 16); break
        case "sspline":
            c.beginPath(); c.moveTo(3, 19); c.bezierCurveTo(8, 3, 16, 3, 21, 19); c.stroke(); c.lineWidth = 1; c.globalAlpha = 0.6; line(3, 19, 8, 5, 16, 5, 21, 19); c.globalAlpha = 1; dot(8, 5); dot(16, 5); break
        case "equation":
            line(4, 3, 4, 20, 21, 20); c.beginPath(); c.moveTo(4, 15); c.bezierCurveTo(9, 0, 13, 26, 20, 7); c.stroke(); break
        case "extend":
            line(3, 12, 11, 12); c.globalAlpha = 0.55; line(13, 12, 18.5, 12); c.globalAlpha = 1; line(15.5, 9, 18.5, 12, 15.5, 15); c.lineWidth = 2.2; line(20.5, 4, 20.5, 20); break
        case "cpattern":
            around(); dot(12, 12); break
        case "silhouette":
            c.beginPath(); c.ellipse(6, 3, 12, 5); c.stroke(); c.beginPath(); c.arc(12, 18.5, 6, 0.08, Math.PI - 0.08); c.stroke(); c.lineWidth = 2.6; line(6, 5.5, 6, 18.5); line(18, 5.5, 18, 18.5); break
        case "section":     // 一块料被一个面切开
            closed(3, 7, 12, 7, 12, 19, 3, 19); c.lineWidth = 1; line(4.5, 17, 10.5, 9); line(4.5, 12.5, 7.5, 8.5); line(7.5, 17.5, 10.5, 13.5); c.lineWidth = 2.2; line(16, 3, 16, 21); c.lineWidth = 1.2; c.globalAlpha = 0.5; closed(16, 7, 21, 7, 21, 19, 16, 19); c.globalAlpha = 1; break
        // ---- 特征 ----
        case "hole_adv":
            line(3, 5, 7.5, 5, 7.5, 11, 10, 11, 10, 19, 14, 19, 14, 11, 16.5, 11, 16.5, 5, 21, 5); break
        case "thread":
            line(7, 3, 7, 21); line(17, 3, 17, 21); line(7, 8, 17, 5.5); line(7, 13, 17, 10.5); line(7, 18, 17, 15.5); break
        case "stud":
            line(3, 19.5, 21, 19.5); closed(9, 19.5, 9, 5, 15, 5, 15, 19.5); line(9, 8.5, 15, 8.5); line(9, 12, 15, 12); break
        case "pattern_curve":
            c.beginPath(); c.moveTo(3, 19); c.bezierCurveTo(8, 3, 16, 21, 21, 5); c.stroke(); ring(5, 14.5, 2.2); ring(12, 12, 2.2); ring(19, 9.5, 2.2); break
        case "pattern_sketch":
            closed(3, 4, 8, 4, 8, 9, 3, 9); closed(14, 3, 19, 3, 19, 8, 14, 8); closed(8, 13, 13, 13, 13, 18, 8, 18); closed(16, 15, 21, 15, 21, 20, 16, 20); break
        case "pattern_table":
            closed(4, 5, 20, 5, 20, 19, 4, 19); line(4, 10, 20, 10); line(4, 14.5, 20, 14.5); line(10, 5, 10, 19); break
        case "pattern_fill":
            closed(3, 4, 21, 4, 21, 20, 3, 20); ring(8.5, 9, 1.9); ring(15.5, 9, 1.9); ring(8.5, 15.5, 1.9); ring(15.5, 15.5, 1.9); break
        case "pattern_variable":
            closed(3, 15, 6.5, 15, 6.5, 19, 3, 19); closed(9, 11.5, 14, 11.5, 14, 19, 9, 19); closed(16.5, 6, 21, 6, 21, 19, 16.5, 19); break
        case "axis":
            line(4, 20, 7.5, 16.5); line(10, 14, 14, 10); line(16.5, 7.5, 20, 4); dot(12, 12); break
        case "com":
            ring(12, 12, 8); line(12, 4, 12, 20); line(4, 12, 20, 12); c.beginPath(); c.moveTo(12, 12); c.arc(12, 12, 8, -Math.PI / 2, 0); c.closePath(); c.fill(); c.beginPath(); c.moveTo(12, 12); c.arc(12, 12, 8, Math.PI / 2, Math.PI); c.closePath(); c.fill(); break
        case "bbox":
            c.lineWidth = 1.2; box(0.6); dot(4, 9); dot(20, 15); break
        case "split":
            closed(4, 5, 20, 5, 20, 19, 4, 19); c.beginPath(); c.moveTo(4, 14); c.bezierCurveTo(9, 6, 15, 20, 20, 10); c.stroke(); break
        case "curve_project":
            c.beginPath(); c.moveTo(4, 7); c.bezierCurveTo(9, 1, 15, 10, 20, 4); c.stroke(); line(12, 8, 12, 14.5); line(9.8, 12.3, 12, 14.5, 14.2, 12.3); c.beginPath(); c.moveTo(3, 21); c.quadraticCurveTo(12, 13, 21, 21); c.stroke(); break
        case "curve_composite":
            line(3, 19, 10, 11); c.beginPath(); c.moveTo(10, 11); c.bezierCurveTo(13, 2, 18, 16, 21, 6); c.stroke(); dot(10, 11); break
        case "curve_xyz":
            c.beginPath(); c.moveTo(4, 18); c.bezierCurveTo(9, 2, 15, 22, 20, 6); c.stroke(); dot(4, 18); dot(12, 12); dot(20, 6); break
        case "curve_points":
            c.beginPath(); c.moveTo(4, 18); c.bezierCurveTo(9, 2, 15, 22, 20, 6); c.stroke(); ring(4, 18, 2.6); ring(12, 12, 2.6); ring(20, 6, 2.6); break
        case "curve_surface":
            c.beginPath(); c.moveTo(3, 9); c.quadraticCurveTo(12, 3, 21, 6); c.lineTo(21, 17); c.quadraticCurveTo(12, 14, 3, 20); c.closePath(); c.stroke(); c.beginPath(); c.moveTo(6, 15); c.bezierCurveTo(10, 6, 14, 17, 18, 9); c.stroke(); break
        case "material":
            closed(12, 3, 21, 8, 12, 13, 3, 8); line(3, 12, 12, 17, 21, 12); line(3, 16, 12, 21, 21, 16); break
        // ---- 视图 ----
        case "zoom_box":
            ring(10, 10, 6.5); line(15, 15, 20.5, 20.5); c.lineWidth = 1.2; closed(7, 8, 13, 8, 13, 12, 7, 12); break
        case "zoom_sel":
            ring(10, 10, 6.5); line(15, 15, 20.5, 20.5); c.lineWidth = 1.2; closed(6.3, 10.6, 9.6, 12.8, 13.7, 9.4, 10.4, 7.2); break
        case "previous":
            ring(13, 12, 6.5); line(17.6, 16.6, 21, 20); line(8.5, 9, 3, 9); line(5.5, 6.2, 3, 9, 5.5, 11.8); break
        case "shaded_edges":
            fill(0.38, 4, 9, 9, 4, 20, 4, 20, 15, 15, 20, 4, 20); box(0); break
        case "shaded":
            fill(0.75, 4, 9, 15, 9, 15, 20, 4, 20); fill(0.40, 4, 9, 9, 4, 20, 4, 15, 9); fill(0.55, 15, 9, 20, 4, 20, 15, 15, 20); break
        case "hlr":
            box(0); break
        case "hlv":
            box(0.55); break
        case "wire":
            c.lineWidth = 1.3; closed(4, 9, 15, 9, 15, 20, 4, 20); closed(9, 4, 20, 4, 20, 15, 9, 15); line(4, 9, 9, 4); line(15, 9, 20, 4); line(15, 20, 20, 15); line(4, 20, 9, 15); break
        case "front":
            fill(0.55, 4, 9, 15, 9, 15, 20, 4, 20); box(0); break
        case "top":
            fill(0.55, 4, 9, 9, 4, 20, 4, 15, 9); box(0); break
        case "right":
            fill(0.55, 15, 9, 20, 4, 20, 15, 15, 20); box(0); break
        case "back":
            fill(0.30, 9, 4, 20, 4, 20, 15, 9, 15); box(0.6); break
        case "left":
            fill(0.30, 4, 9, 9, 4, 9, 15, 4, 20); box(0.6); break
        case "bottom":
            fill(0.30, 4, 20, 9, 15, 20, 15, 15, 20); box(0.6); break
        case "eye":
            eye(); break
        case "eye_off":
            eye(); c.lineWidth = 2; line(4.5, 19.5, 19.5, 4.5); break
        case "isolate":     // 孤立: 中间一块留着, 四周的只剩淡淡的角
            fill(0.85, 8, 8, 16, 8, 16, 16, 8, 16); closed(8, 8, 16, 8, 16, 16, 8, 16)
            c.globalAlpha = 0.45; c.lineWidth = 1.2
            line(3, 6, 3, 3, 6, 3); line(18, 3, 21, 3, 21, 6); line(21, 18, 21, 21, 18, 21); line(6, 21, 3, 21, 3, 18)
            c.globalAlpha = 1; c.lineWidth = 1.7; break
        case "tree_expand": // 全部展开: 两个往下的箭头
            line(7, 6, 12, 11, 17, 6); line(7, 13, 12, 18, 17, 13); break
        case "tree_collapse":
            line(7, 11, 12, 6, 17, 11); line(7, 18, 12, 13, 17, 18); break
        case "tree_chevron":    // 设计树的展开箭头 (朝右, 展开时界面把它转 90°)
            line(9.5, 6.5, 15, 12, 9.5, 17.5); break
        case "tree":        // 设计树页签: 一个根 + 往下分出去的几层
            closed(4, 3.5, 10, 3.5, 10, 8.5, 4, 8.5); line(7, 8.5, 7, 18, 12, 18); line(7, 12, 12, 12)
            closed(12, 10, 20, 10, 20, 14, 12, 14); closed(12, 16, 20, 16, 20, 20, 12, 20); break
        case "props":       // PropertyManager 页签: 一张单子, 每行一个名称 + 值
            closed(4, 3.5, 20, 3.5, 20, 20.5, 4, 20.5); line(7.5, 8.5, 10.5, 8.5); line(13, 8.5, 16.5, 8.5)
            line(7.5, 12.5, 10.5, 12.5); line(13, 12.5, 16.5, 12.5); line(7.5, 16.5, 10.5, 16.5); line(13, 16.5, 16.5, 16.5); break
        case "appearance":  // 一个带高光的球
            ring(12, 12, 8.5); c.beginPath(); c.arc(9, 8.8, 2.3, 0, Math.PI * 2); c.fill(); c.globalAlpha = 0.35; c.beginPath(); c.arc(12, 12, 8.5, 0.15, Math.PI * 0.85); c.closePath(); c.fill(); c.globalAlpha = 1; break
        case "scene":
            closed(3, 5, 21, 5, 21, 19, 3, 19); line(3, 16.5, 9, 10.5, 13, 14.5, 16, 11.5, 21, 16.5); c.beginPath(); c.arc(16.5, 8.5, 1.5, 0, Math.PI * 2); c.fill(); break
        case "settings":
            line(4, 7, 20, 7); line(4, 12, 20, 12); line(4, 17, 20, 17); c.beginPath(); c.arc(9, 7, 2.4, 0, Math.PI * 2); c.fill(); c.beginPath(); c.arc(15.5, 12, 2.4, 0, Math.PI * 2); c.fill(); c.beginPath(); c.arc(7.5, 17, 2.4, 0, Math.PI * 2); c.fill(); break
        case "perspective":
            closed(2.5, 19, 21.5, 19, 16, 6, 8, 6); line(12, 6, 12, 19); line(5.2, 12.5, 18.8, 12.5); break
        case "cartoon":
            c.lineWidth = 2.8; ring(12, 12, 7.5); c.lineWidth = 1.3; c.beginPath(); c.arc(12, 12, 4.2, Math.PI * 0.1, Math.PI * 0.9); c.stroke(); break
        case "save_view":
            closed(3, 8, 15, 8, 15, 18, 3, 18); closed(15, 11.5, 21, 8.5, 21, 17.5, 15, 14.5); line(9, 10.5, 9, 15.5); line(6.5, 13, 11.5, 13); break
        case "check":
            c.lineWidth = 2.1; line(5, 12.5, 10, 17.5, 19, 6.5); break
        case "sketch":      // 平面上的一支笔
            closed(3, 17, 9, 21, 21, 17, 15, 13); line(8, 15, 16, 5); line(16, 5, 18.5, 7); line(18.5, 7, 10.5, 17); line(8, 15, 10.5, 17); break
        case "extrude":     // 底面 + 向上的箭头
            closed(4, 17, 12, 21, 20, 17, 12, 13); line(12, 13, 12, 3); line(8.5, 6.5, 12, 3, 15.5, 6.5); break
        case "fillet":      // 圆掉的角
            c.beginPath(); c.moveTo(4, 20); c.lineTo(4, 12); c.arc(12, 12, 8, Math.PI, Math.PI * 1.5); c.lineTo(20, 4); c.stroke(); break
        case "chamfer":     // 切掉的角
            line(4, 20, 4, 11, 11, 4, 20, 4); break
        case "select":      // 箭头光标
            closed(6, 3, 6, 18, 10, 14.5, 13, 21, 15.5, 19.8, 12.6, 13.5, 18, 13.5); break
        case "line":
            line(5, 19, 19, 5); dot(5, 19); dot(19, 5); break
        case "rect":
            closed(4, 6, 20, 6, 20, 18, 4, 18); dot(4, 6); dot(20, 18); break
        case "circle":
            c.beginPath(); c.arc(12, 12, 8, 0, Math.PI * 2); c.stroke(); dot(12, 12); break
        case "finish":
            c.lineWidth = 2.2; line(5, 12.5, 10, 17.5, 19, 6.5); break
        case "cancel":
            c.lineWidth = 2.0; line(6, 6, 18, 18); line(18, 6, 6, 18); break
        case "undo":
            line(8, 5, 4, 9, 8, 13); c.beginPath(); c.moveTo(4, 9); c.lineTo(14, 9); c.arc(14, 14, 5, -Math.PI / 2, Math.PI / 2); c.lineTo(8, 19); c.stroke(); break
        case "redo":
            line(16, 5, 20, 9, 16, 13); c.beginPath(); c.moveTo(20, 9); c.lineTo(10, 9); c.arc(10, 14, 5, -Math.PI / 2, Math.PI / 2, true); c.lineTo(16, 19); c.stroke(); break
        case "drawing":     // 一张图纸: 上面两个视图, 右下角标题栏
            closed(3, 4, 21, 4, 21, 20, 3, 20); closed(6, 7, 12, 7, 12, 11, 6, 11); ring(8.5, 15.5, 2.2); line(14, 16, 21, 16); line(14, 16, 14, 20); break
        case "new":
            closed(6, 3, 14, 3, 18, 7, 18, 21, 6, 21); line(14, 3, 14, 7, 18, 7); break
        case "open":
            closed(3, 6, 9, 6, 11, 8, 21, 8, 21, 19, 3, 19); break
        case "save":
            closed(4, 4, 17, 4, 20, 7, 20, 20, 4, 20); closed(8, 4, 8, 9, 15, 9, 15, 4); closed(7, 20, 7, 14, 17, 14, 17, 20); break
        case "export":
            line(12, 4, 12, 15); line(8, 8, 12, 4, 16, 8); line(4, 14, 4, 20, 20, 20, 20, 14); break
        case "plane":
            closed(3, 16, 10, 20, 21, 12, 14, 8); break
        case "fit":
            line(4, 9, 4, 4, 9, 4); line(15, 4, 20, 4, 20, 9); line(20, 15, 20, 20, 15, 20); line(9, 20, 4, 20, 4, 15); closed(9, 9, 15, 9, 15, 15, 9, 15); break
        case "cube":        // 视图方向
            closed(12, 3, 20, 7.5, 20, 16.5, 12, 21, 4, 16.5, 4, 7.5); line(4, 7.5, 12, 12, 20, 7.5); line(12, 12, 12, 21); break
        case "normal":      // 正对着一个面看
            closed(5, 8, 19, 8, 19, 20, 5, 20); line(12, 2, 12, 13); line(9, 10, 12, 13, 15, 10); break
        case "folder":      // 设计树里的文件夹
            closed(3, 6.5, 9.5, 6.5, 11.5, 9, 21, 9, 21, 19, 3, 19); line(3, 11.5, 21, 11.5); break
        case "folder_open": // 展开着的文件夹
            closed(3, 6.5, 9.5, 6.5, 11.5, 9, 19, 9, 19, 11.5); closed(3, 19, 6, 11.5, 22, 11.5, 19, 19); line(3, 6.5, 3, 19); break
        case "part":        // 零件 (设计树的根)
            closed(12, 3, 20, 7.5, 20, 16.5, 12, 21, 4, 16.5, 4, 7.5); line(4, 7.5, 12, 12, 20, 7.5); line(12, 12, 12, 21); break
        case "origin":      // 原点: 三根轴
            line(12, 13, 12, 4); line(12, 13, 20, 17); line(12, 13, 4, 17); dot(12, 13); break
        case "cut":         // 往下切进去
            closed(4, 9, 12, 13, 20, 9, 12, 5); line(12, 9, 12, 21); line(8.5, 17.5, 12, 21, 15.5, 17.5); break
        case "exit":        // 退出草图: 平面 + 往外的箭头
            closed(3, 17, 9, 21, 21, 17, 15, 13); line(12, 15, 12, 4); line(8.5, 7.5, 12, 4, 15.5, 7.5); break
        case "arc":
            c.beginPath(); c.arc(6, 19, 13, -Math.PI / 2, 0); c.stroke(); dot(6, 19); dot(6, 6); dot(19, 19); break
        case "slot":
            c.beginPath(); c.moveTo(8, 8); c.lineTo(16, 8); c.arc(16, 12, 4, -Math.PI / 2, Math.PI / 2); c.lineTo(8, 16); c.arc(8, 12, 4, Math.PI / 2, Math.PI * 1.5); c.stroke(); break
        case "ngon":
            closed(12, 3, 19.8, 7.5, 19.8, 16.5, 12, 21, 4.2, 16.5, 4.2, 7.5); break
        case "ellipse":
            c.beginPath(); c.ellipse(3, 6.5, 18, 11); c.stroke(); dot(12, 12); break
        case "spline":
            c.beginPath(); c.moveTo(3, 17); c.bezierCurveTo(8, 1, 14, 23, 21, 7); c.stroke(); dot(3, 17); dot(21, 7); break
        case "point":
            line(12, 4, 12, 8); line(12, 16, 12, 20); line(4, 12, 8, 12); line(16, 12, 20, 12); c.beginPath(); c.arc(12, 12, 2.4, 0, Math.PI * 2); c.fill(); break
        case "text":
            line(6, 20, 12, 4, 18, 20); line(8.3, 14, 15.7, 14); break
        case "trim":        // 一条线中间被剪掉一段
            line(3, 12, 8.5, 12); line(15.5, 12, 21, 12); line(9.5, 7, 14.5, 17); line(14.5, 7, 9.5, 17); break
        case "offset":      // 两条平行的折线
            line(4, 20, 4, 6, 18, 6); line(9, 20, 9, 11, 18, 11); break
        case "mirror":
            line(12, 2.5, 12, 6); line(12, 9, 12, 15); line(12, 18, 12, 21.5); closed(9, 7, 9, 17, 3.5, 17); closed(15, 7, 15, 17, 20.5, 17); break
        case "pattern":
            closed(2.5, 9.5, 7.5, 9.5, 7.5, 14.5, 2.5, 14.5); closed(9.5, 9.5, 14.5, 9.5, 14.5, 14.5, 9.5, 14.5); closed(16.5, 9.5, 21.5, 9.5, 21.5, 14.5, 16.5, 14.5); break
        case "move":
            line(12, 3, 12, 21); line(3, 12, 21, 12); line(9.5, 5.5, 12, 3, 14.5, 5.5); line(9.5, 18.5, 12, 21, 14.5, 18.5); line(5.5, 9.5, 3, 12, 5.5, 14.5); line(18.5, 9.5, 21, 12, 18.5, 14.5); break
        case "convert":     // 实体的边落到草图平面上
            closed(5, 3, 15, 3, 15, 10, 5, 10); line(10, 10, 10, 16); line(7.3, 13.5, 10, 16.2, 12.7, 13.5); c.lineWidth = 2.2; line(3, 20.5, 19, 20.5); break
        case "dimension":   // 两条界线之间的尺寸线
            line(4, 4, 4, 20); line(20, 4, 20, 20); line(4, 12, 20, 12); line(7.5, 9, 4.5, 12, 7.5, 15); line(16.5, 9, 19.5, 12, 16.5, 15); break
        case "relation":    // 垂直符号
            c.lineWidth = 2; line(4, 19, 20, 19); line(12, 19, 12, 4); c.lineWidth = 1.4; line(12, 14.5, 16.5, 14.5, 16.5, 19); break
        case "sketch3d":    // 三根坐标轴
            line(11, 13, 11, 3); line(11, 13, 21, 16); line(11, 13, 4, 20); dot(11, 3); dot(21, 16); dot(4, 20); break
        case "repair":      // 把断开的线接上
            line(3, 15, 9, 15); line(15, 15, 21, 15); line(12, 4, 12, 11); line(9, 8.5, 12, 11.5, 15, 8.5); dot(9, 15); dot(15, 15); break
        case "snap":        // 磁铁
            c.beginPath(); c.moveTo(6, 4); c.lineTo(6, 13); c.arc(12, 13, 6, Math.PI, 0, true); c.lineTo(18, 4); c.stroke(); line(3.5, 7.5, 8.5, 7.5); line(15.5, 7.5, 20.5, 7.5); break
        case "rapid":       // 闪电
            closed(13.5, 2, 5, 13.5, 11, 13.5, 9.5, 22, 19, 10, 13, 10); break
        case "revolve":     // 轴 + 绕着它的一圈
            line(12, 2.5, 12, 21.5); c.beginPath(); c.ellipse(4, 9, 16, 7); c.stroke(); line(17.5, 8, 19.6, 11, 16.2, 12); break
        case "sweep":       // 起点的轮廓 + 路径
            c.beginPath(); c.arc(6, 17, 3, 0, Math.PI * 2); c.stroke(); c.beginPath(); c.moveTo(9, 16); c.bezierCurveTo(13, 14, 11, 6, 20, 5); c.stroke(); dot(20, 5); break
        case "loft":        // 上小下大两个轮廓
            c.beginPath(); c.ellipse(3, 15, 18, 6); c.stroke(); c.beginPath(); c.ellipse(8, 3, 8, 4); c.stroke(); line(3, 18, 8, 5); line(21, 18, 16, 5); break
        case "boundary":    // 侧边是曲线的过渡
            c.beginPath(); c.moveTo(4, 20); c.quadraticCurveTo(10, 13, 8, 4); c.lineTo(16, 4); c.quadraticCurveTo(14, 13, 20, 20); c.closePath(); c.stroke(); break
        case "hole":
            c.beginPath(); c.arc(12, 12, 8.5, 0, Math.PI * 2); c.stroke(); c.beginPath(); c.arc(12, 12, 3.6, 0, Math.PI * 2); c.stroke(); break
        case "rib":         // L 形里的一道斜筋
            line(4, 3, 4, 20, 21, 20); line(4, 8, 16, 20); line(8, 12, 8, 20); break
        case "draft":       // 往里斜的侧面
            line(3, 20, 21, 20); closed(6, 20, 9.5, 5, 14.5, 5, 18, 20); line(6, 20, 6, 5); break
        case "shell":       // 掏空, 上面开口
            line(4, 5, 4, 20, 20, 20, 20, 5); line(7.5, 5, 7.5, 16.5, 16.5, 16.5, 16.5, 5); break
        case "wrap":        // 圆柱上贴一块
            c.beginPath(); c.ellipse(5, 2.5, 14, 5); c.stroke(); line(5, 5, 5, 19); line(19, 5, 19, 19); c.beginPath(); c.arc(12, 19, 7, 0, Math.PI); c.stroke(); closed(9, 11, 15, 11.8, 15, 16.8, 9, 16); break
        case "reference":   // 基准面 + 轴
            closed(3, 17, 10, 21, 21, 13, 14, 9); line(12, 15, 12, 3); line(9.8, 5.2, 12, 3, 14.2, 5.2); break
        case "curve":       // 螺旋线
            c.beginPath(); c.moveTo(5, 20); c.bezierCurveTo(22, 20, 22, 15, 12, 15); c.bezierCurveTo(2, 15, 2, 10, 12, 10); c.bezierCurveTo(22, 10, 22, 5, 12, 4); c.stroke(); break
        case "rel_horizontal":      // 几何关系: 一条横线 + 两头的小竖杠
            line(4, 12, 20, 12); line(4, 9, 4, 15); line(20, 9, 20, 15); break
        case "rel_vertical":
            line(12, 4, 12, 20); line(9, 4, 15, 4); line(9, 20, 15, 20); break
        case "rel_parallel":
            line(6, 20, 13, 4); line(12, 20, 19, 4); break
        case "rel_perpendicular":
            line(4, 19, 20, 19); line(12, 19, 12, 4); break
        case "rel_collinear":
            line(3, 15, 9.5, 11.5); line(14.5, 8.8, 21, 5.3); dot(12, 10.2); break
        case "rel_equal":
            line(5, 9, 19, 9); line(5, 15, 19, 15); break
        case "rel_concentric":
            ring(12, 12, 8); ring(12, 12, 3.5); break
        case "rel_coincident":
            ring(12, 12, 4.5); dot(12, 12); line(3, 21, 8.5, 15.5); break
        case "rel_tangent":
            ring(11, 14, 6.5); line(3, 5.5, 21, 9.5); break
        case "lock":
            closed(6, 11, 18, 11, 18, 20, 6, 20)
            c.beginPath(); c.moveTo(8.5, 11); c.lineTo(8.5, 8); c.quadraticCurveTo(8.5, 4, 12, 4); c.quadraticCurveTo(15.5, 4, 15.5, 8); c.lineTo(15.5, 11); c.stroke()
            dot(12, 15.5); break
        case "stress":      // 一头固定的梁, 另一头有力往下压
            line(4, 4, 4, 20); line(2, 7, 4, 5); line(2, 12, 4, 10); line(2, 17, 4, 15)
            c.beginPath(); c.moveTo(4, 9); c.lineTo(20, 9); c.quadraticCurveTo(13, 14, 4, 15); c.stroke()
            line(19, 2.5, 19, 7.5); line(16.8, 5.3, 19, 7.5, 21.2, 5.3); break
        case "wind":        // 三道气流
            c.beginPath(); c.moveTo(3, 8); c.lineTo(14, 8); c.quadraticCurveTo(18, 8, 17.5, 5); c.quadraticCurveTo(16.5, 2.8, 14.5, 4); c.stroke()
            line(3, 12, 20, 12)
            c.beginPath(); c.moveTo(3, 16); c.lineTo(13, 16); c.quadraticCurveTo(17, 16, 16.5, 19); c.quadraticCurveTo(15.5, 21.2, 13.5, 20); c.stroke(); break
        case "assembly":    // 一个零件正往另一个里装
            closed(3, 12, 21, 12, 21, 21, 3, 21); line(9, 12, 9, 16, 15, 16, 15, 12)
            closed(9.5, 2.5, 14.5, 2.5, 14.5, 8, 9.5, 8); line(12, 9, 12, 14); line(10.2, 12.2, 12, 14, 13.8, 12.2); break
        case "process":     // 绑定工艺: 一个零件挂着一块标签
            closed(3, 9, 12, 4.5, 21, 9, 12, 13.5); line(3, 9, 3, 15, 12, 19.5, 12, 13.5); line(12, 19.5, 14, 18.5)
            closed(15.5, 14, 21, 14, 22.5, 17, 21, 20, 15.5, 20); dot(18, 17); break
        case "drc":         // 设计检查: 盾牌里一个勾
            closed(12, 2.5, 20, 5.5, 20, 12, 12, 21.5, 4, 12, 4, 5.5); c.lineWidth = 2; line(8, 12, 11, 15, 16.5, 8.5); break
        case "rules":       // 设计规则: 一把尺子 + 上下两道公差线
            closed(3, 9, 21, 9, 21, 15, 3, 15); line(7, 9, 7, 12); line(11, 9, 11, 12.5); line(15, 9, 15, 12); line(19, 9, 19, 12.5)
            c.lineWidth = 1.2; line(3, 5, 21, 5); line(3, 19, 21, 19); break
        case "clash":       // 两个叠在一起的方块, 叠的那块涂实
            closed(3, 3, 14, 3, 14, 14, 3, 14); closed(10, 10, 21, 10, 21, 21, 10, 21); fill(0.55, 10, 10, 14, 10, 14, 14, 10, 14); break
        case "order":       // 1 2 3 的台阶
            line(3, 20, 3, 15, 9, 15, 9, 10, 15, 10, 15, 5, 21, 5); line(18, 2.5, 21, 5, 18, 7.5); break
        case "up":
            line(12, 19, 12, 5); line(6.5, 10.5, 12, 5, 17.5, 10.5); break
        case "down":
            line(12, 5, 12, 19); line(6.5, 13.5, 12, 19, 17.5, 13.5); break
        case "plus":
            line(12, 5, 12, 19); line(5, 12, 19, 12); break
        case "play":
            closed(7, 4.5, 19, 12, 7, 19.5); break
        case "pause":
            line(8.5, 5, 8.5, 19); line(15.5, 5, 15.5, 19); break
        case "hinge":       // 运动副 (铰链): 一扇门 + 绕着门轴的一道弧
            line(5, 3.5, 5, 20.5); closed(5, 5, 13, 7.5, 13, 18.5, 5, 20); c.beginPath(); c.arc(5, 12, 13, -0.55, 0.55); c.stroke()
            line(17, 18.4, 15.9, 19.5, 17.4, 20); break
        case "motion":      // 动画: 一条时间轴 + 播放三角
            closed(3, 6, 21, 6, 21, 18, 3, 18); closed(10, 9, 15, 12, 10, 15); line(3, 21, 21, 21); dot(8, 21); break
        case "screw":       // 一颗螺丝: 圆柱头 + 带螺纹的杆
            closed(6, 3, 18, 3, 18, 8, 6, 8); line(9.5, 8, 9.5, 19, 12, 21.5, 14.5, 19, 14.5, 8)
            line(9.5, 11.5, 14.5, 10); line(9.5, 14.5, 14.5, 13); line(9.5, 17.5, 14.5, 16); break
        case "measure":     // 一把斜放的尺子
            closed(3, 15.5, 15.5, 3, 21, 8.5, 8.5, 21); line(7, 12.5, 9, 14.5); line(10, 9.5, 13, 12.5); line(13, 6.5, 15, 8.5); break
        case "trash":
            line(4.5, 7, 19.5, 7); line(9.5, 7, 9.5, 4.5, 14.5, 4.5, 14.5, 7); line(6.5, 7, 7.5, 20, 16.5, 20, 17.5, 7); line(10.3, 10.5, 10.3, 16.5); line(13.7, 10.5, 13.7, 16.5); break
        case "flip":        // 两个相对的箭头
            line(4, 9, 19, 9); line(15, 5, 19, 9, 15, 13); line(20, 16, 5, 16); line(9, 12, 5, 16, 9, 20); break
        case "gear":
            ring(12, 12, 3); ring(12, 12, 6.4); c.lineWidth = 2.4
            for (let k = 0; k < 8; k++) { const t = k * Math.PI / 4; line(12 + 6.6 * Math.cos(t), 12 + 6.6 * Math.sin(t), 12 + 9.2 * Math.cos(t), 12 + 9.2 * Math.sin(t)) }
            break
        case "edit":        // 一支笔
            closed(4, 20, 5, 15.5, 15.5, 5, 19, 8.5, 8.5, 19); line(13.2, 7.3, 16.7, 10.8); break
        case "suppress":    // 压下去
            c.globalAlpha = 0.5; closed(4.5, 4.5, 19.5, 4.5, 19.5, 19.5, 4.5, 19.5); c.globalAlpha = 1; line(12, 7.5, 12, 16.5); line(8, 12.5, 12, 16.5, 16, 12.5); break
        case "unsuppress":
            c.globalAlpha = 0.5; closed(4.5, 4.5, 19.5, 4.5, 19.5, 19.5, 4.5, 19.5); c.globalAlpha = 1; line(12, 16.5, 12, 7.5); line(8, 11.5, 12, 7.5, 16, 11.5); break
        case "rollback":    // 回退线往上提
            c.lineWidth = 2.2; line(4, 19, 20, 19); c.lineWidth = 1.7; line(12, 15, 12, 4.5); line(8, 8.5, 12, 4.5, 16, 8.5); break
        case "roll_end":    // 回退线放回最下面
            c.lineWidth = 2.2; line(4, 5, 20, 5); c.lineWidth = 1.7; line(12, 9, 12, 19.5); line(8, 15.5, 12, 19.5, 16, 15.5); break
        case "select_other":    // 前面一个面, 后面还有一个
            c.globalAlpha = 0.45; closed(4, 4, 14.5, 4, 14.5, 14.5, 4, 14.5); c.globalAlpha = 1; closed(9.5, 9.5, 20, 9.5, 20, 20, 9.5, 20); break
        case "same_faces":
            closed(3, 4.5, 10.5, 4.5, 10.5, 12, 3, 12); closed(13.5, 4.5, 21, 4.5, 21, 12, 13.5, 12); line(7, 16, 17, 16); line(7, 19.5, 17, 19.5); break
        case "back_face":   // 盒子后面的那个面
            box(0.5); fill(0.45, 9, 4, 20, 4, 20, 15, 9, 15); break
        case "keyboard":
            closed(2.5, 6.5, 21.5, 6.5, 21.5, 17.5, 2.5, 17.5); dot(6.6, 10.4); dot(10.2, 10.4); dot(13.8, 10.4); dot(17.4, 10.4); line(7.5, 14.3, 16.5, 14.3); break
        case "gesture":     // 手势轮
            ring(12, 12, 2.2); around(); break
        case "search":
            ring(10.5, 10.5, 6); line(15, 15, 20.5, 20.5); break
        case "reset":       // 转回去的箭头
            c.beginPath(); c.arc(12, 12.5, 7.5, Math.PI * 0.2, Math.PI * 1.75); c.stroke(); line(13.2, 5.6, 17.6, 7.4, 16.6, 2.9); break
        case "ai":          // 对话气泡
            closed(4, 5, 20, 5, 20, 15.5, 11.5, 15.5, 7.5, 19.5, 7.5, 15.5, 4, 15.5); dot(9, 10.3); dot(15, 10.3); break
        case "copy":
            closed(8.5, 8.5, 19.5, 8.5, 19.5, 20, 8.5, 20); line(5, 15.5, 5, 4, 15, 4); break
        case "theme":
            c.beginPath(); c.arc(12, 12, 8, 0, Math.PI * 2); c.stroke(); c.beginPath(); c.arc(12, 12, 8, -Math.PI / 2, Math.PI / 2); c.closePath(); c.fill(); break
        case "min":
            c.lineWidth = 1.2; line(6, 12.5, 18, 12.5); break
        case "max":
            c.lineWidth = 1.2; closed(6.5, 6.5, 17.5, 6.5, 17.5, 17.5, 6.5, 17.5); break
        case "restore":
            c.lineWidth = 1.2; closed(6, 9, 15, 9, 15, 18, 6, 18); line(9, 9, 9, 6, 18, 6, 18, 15, 15, 15); break
        case "close":
            c.lineWidth = 1.2; line(6.5, 6.5, 17.5, 17.5); line(17.5, 6.5, 6.5, 17.5); break
        }
    }
}
