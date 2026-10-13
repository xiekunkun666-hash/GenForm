// AxisTriad.qml - 视图左下角的坐标系: 三根轴跟着视角转, 让人随时知道哪边是 X / Y / Z。
// axes 是视图给的 [[右, 下, 远]...] (每根世界轴在屏幕上的方向)。朝里的轴画淡一点、先画。
import QtQuick

Canvas {
    id: triad
    property var axes: []
    width: 104; height: 104
    onAxesChanged: requestPaint()
    Connections { target: Theme; function onDarkModeChanged() { triad.requestPaint() } }

    onPaint: {
        const c = getContext("2d")
        c.reset()
        if (!axes || axes.length !== 3) return
        const centre = width / 2, reach = 34
        const names = ["X", "Y", "Z"], tints = [Theme.cAxisX, Theme.cAxisY, Theme.cAxisZ]
        const order = [0, 1, 2].sort((a, b) => axes[b][2] - axes[a][2])      // 远的先画
        c.lineCap = "round"
        c.font = "bold 12px '" + Theme.font + "'"
        c.textAlign = "center"; c.textBaseline = "middle"
        for (const index of order) {
            const axis = axes[index]
            const x = centre + axis[0] * reach, y = centre + axis[1] * reach
            c.globalAlpha = axis[2] > 0.15 ? 0.45 : 1.0
            c.strokeStyle = tints[index]; c.fillStyle = tints[index]
            c.lineWidth = 2.2
            c.beginPath(); c.moveTo(centre, centre); c.lineTo(x, y); c.stroke()
            c.beginPath(); c.arc(x, y, 2.6, 0, Math.PI * 2); c.fill()
            const flat = Math.hypot(axis[0], axis[1])
            if (flat > 0.25)                                                    // 正对着眼睛的那根轴不写字 (字会压在原点上)
                c.fillText(names[index], x + axis[0] / flat * 10, y + axis[1] / flat * 10)
        }
        c.globalAlpha = 1.0
        c.fillStyle = Theme.cTextSec
        c.beginPath(); c.arc(centre, centre, 2.4, 0, Math.PI * 2); c.fill()
    }
}
