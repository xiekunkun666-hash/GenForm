"""仿真页的信号: 放在一个普通基类里, 混入类的属性直接拿它当 notify (模块里有同名别名)。"""
from __future__ import annotations

from PySide6.QtCore import Signal


class Signals:
    """仿真页发给界面的信号 (Simulation 继承它)。"""
    changed = Signal()
    editRequested = Signal(int)         # 右键菜单里点了 "编辑位置": 左栏翻到属性管理器, 显示这个零部件的位置


changed = Signals.changed
