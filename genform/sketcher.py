"""草图编辑器: 在基准面上用鼠标画图形、拖动修改、填精确尺寸。纯数据和几何 (见 sketchgeom.py), 不碰界面库。

坐标都是草图平面内的二维坐标 (mm)。视图把鼠标位置换算成平面坐标再喂进来, pixel 是当前一个屏幕像素
对应多少毫米 — 捕捉和 "点没点中" 的容差都按屏幕像素算, 所以放大缩小后手感一样。

画图工具 (画完一个工具不变, 可以接着画; 刚画的处于选中状态, 面板里可以直接改成精确尺寸):
    line     连续点出一段段直线, 点回起点闭合; 回车 / 双击 / Esc 结束这一串 (centerline: 同样画法, 画出来的是构造线)
    midline  中点 → 一端 (另一端对称)      crect    中心 + 一个角
    rect3    一条边的两端 → 对边            crect3   中心 → 一边的中点 → 一个角        pgram  三个角
    cslot    中心 → 一个圆心 → 槽宽         circle3  圆周上三个点
    aslot3   弧的起点 → 终点 → 弧上一点 → 槽宽     caslot  圆心 → 起点 → 终点 → 槽宽
    sspline  样式样条: 点的是控制点          equation 点一下放一条方程式曲线, 式子在面板里改
    rect     两个对角 (或按住拖出)          circle   圆心 + 圆周上一点 (或按住拖出)
    arc      圆心 → 起点 → 终点             slot     两个圆心 → 槽宽
    ngon     中心 + 一个顶点 (边数在面板里)   ellipse  中心 → 长轴端点 → 短轴
    spline   连续点出经过的点, 回车 / 双击结束, 点回起点闭合
    point    点一下放一个点                 text     点一下放一行字; 先选中一条曲线再点工具 = 沿这条曲线排
修改工具:
    select   点选 (Ctrl 加选), 空白处拖出方框框选, 拖图形移动, 拖控制点改形状, 双击选中首尾相接的一串
    fillet   点两条直线相交的尖角            trim     点要剪掉的那一段        extend  点要延长的那一头
    dimension 智能尺寸: 点一个图形改它的主尺寸; 再点另一处 (点或线) 拉出距离标注, 点一下放下再改数 (改一次, 不是约束)
    offset   点一个图形, 再点一下定距离和方向  convert  点实体的边 (投影到草图平面上的) 把它拷进草图
    mirror   先选图形, 再点两点定镜向轴       move     先选图形, 再点起点和终点
带面板的操作 (operation): pattern 线性阵列, cpattern 圆周阵列, relation 几何关系 (摆一次), repair 检查修复。

这里没有约束求解: 图形之间互不关联, 尺寸就是图形自己的参数。

实现在 genform/sketch/ 包里 (editor 主类 + snapping / mouse / building / dimension / selecting /
panels / relations 几个混入类, common 放常量); 这里只把对外用的名字转出去。
"""
from .sketch.editor import SketchEditor
from .sketch.common import (
    handles, grid_step, describe, ALL_SNAPS, QUICK_SNAPS, SNAP_NAMES, TOOLS, DIMENSIONS, SNAP_PIXELS, HIT_PIXELS,
    DRAG_PIXELS, STEPS, DRAG_TOOLS, CHAIN_TOOLS, SPLINE_TOOLS, GRID_STEPS, TOOL_TITLES, PROPERTY_TITLES)

__all__ = [
    'SketchEditor', 'handles', 'grid_step', 'describe', 'ALL_SNAPS', 'QUICK_SNAPS', 'SNAP_NAMES', 'TOOLS',
    'DIMENSIONS', 'SNAP_PIXELS', 'HIT_PIXELS', 'DRAG_PIXELS', 'STEPS', 'DRAG_TOOLS', 'CHAIN_TOOLS', 'SPLINE_TOOLS',
    'GRID_STEPS', 'TOOL_TITLES', 'PROPERTY_TITLES']
