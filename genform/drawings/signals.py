"""工程图的信号: 放在一个普通基类里, 各个混入类的属性直接拿它当 notify (模块里有同名别名)。"""
from __future__ import annotations

from PySide6.QtCore import Signal


class Signals:
    """工程图发给界面的信号 (Drawing 继承它)。"""
    changed = Signal()


changed = Signals.changed
