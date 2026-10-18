"""三维视图的信号: 放在一个普通基类里, 各个混入类的属性直接拿它们当 notify (模块里有同名别名)。"""
from __future__ import annotations

from PySide6.QtCore import Signal


class Signals:
    """三维视图发给界面 / 控制器的信号 (Viewport 继承它)。"""
    picked = Signal(str, object, bool)      # ('face'|'edge'|'sketch'|'plane'|'', 编号 / 特征 id / 基准面名, 是否加选)
    boxed = Signal(object, bool)            # 框选的结果 {'faces': [...], 'edges': [...], 'sketches': [...]}, 是否加选
    bandChanged = Signal()                  # 选择框出现 / 变了 / 没了
    hoverChanged = Signal(str)              # 光标下的东西的文字说明 (状态栏用)
    shotSaved = Signal(str)                 # 截图存好了 (路径; 失败为空字符串)
    sketchEdited = Signal()                 # 草图编辑器里的内容变了 (画完一笔、选中变了、拖完了)
    darkChanged = Signal()
    labelsChanged = Signal()
    axesChanged = Signal()                  # 视角转了 (左下角的坐标系跟着转)
    planesVisibleChanged = Signal()
    gestureChanged = Signal()               # 手势轮出现 / 消失 / 指向的格子变了
    handleDragged = Signal(float)           # 拉伸的箭头被拖到了离草图平面多远
    gestureTriggered = Signal(int)          # 划中了第几格
    menuRequested = Signal(str, object)     # 右键单击 (没拖成手势): 光标下是什么 ('face'|'edge'|'sketch'|'plane'|'', 编号 / id)
    zoomChanged = Signal()                  # 局部放大: 开始等用户拖框 / 框的大小变了 / 结束
    jointDragged = Signal(int, float)       # 装配体里按住车门拖: (零部件序号, 这一下转了多少度 / 滑了多少 mm)
    jointReleased = Signal()                # 拖完松手了


picked = Signals.picked
boxed = Signals.boxed
bandChanged = Signals.bandChanged
hoverChanged = Signals.hoverChanged
shotSaved = Signals.shotSaved
sketchEdited = Signals.sketchEdited
darkChanged = Signals.darkChanged
labelsChanged = Signals.labelsChanged
axesChanged = Signals.axesChanged
planesVisibleChanged = Signals.planesVisibleChanged
gestureChanged = Signals.gestureChanged
handleDragged = Signals.handleDragged
gestureTriggered = Signals.gestureTriggered
zoomChanged = Signals.zoomChanged
jointDragged = Signals.jointDragged
jointReleased = Signals.jointReleased
