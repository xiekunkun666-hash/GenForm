"""界面控制器: QML 和会话之间的桥。

QML 只读这里的属性、调这里的槽; 这里把每个操作变成一条命令交给会话 (和 AI 接口同一条路),
再把会话的变化 (特征列表、模型、忙碌状态) 报给 QML 和三维视图。

草图编辑是这里唯一的 "模式": 进入后左键交给草图编辑器, 画的东西先只在编辑器里, 点 "完成草图" 才变成
一条 sketch / edit_feature 命令 — 所以放弃草图不会在历史里留下任何东西。

实现在 genform/controller/ 包里 (controller 主类 + 按职责分的混入类, signals 放信号,
common 放表); 这里只把对外用的名字转出去。
"""
from .controller.controller import AppController
from .controller.common import solid_blocks, TOOL_HINTS, OPERATION_HINTS

__all__ = ['AppController', 'solid_blocks', 'TOOL_HINTS', 'OPERATION_HINTS']
