"""控制器的信号: 放在一个普通基类里, 各个混入类的属性直接拿它们当 notify (模块里有同名别名)。"""
from __future__ import annotations

from PySide6.QtCore import Signal


class Signals:
    """控制器发给界面的信号 (AppController 继承它)。"""
    changed = Signal()              # 特征列表 / 忙碌 / 撤销状态 / 标题 / 选择
    formChanged = Signal()
    sketchChanged = Signal()        # 进入或退出草图、换工具、等着选基准面
    hoverTextChanged = Signal()
    notice = Signal(str)            # 要让用户看到的一句话 (出错原因等)
    viewChanged = Signal()          # 显示样式 / 布景 / 剖切 / 显示哪些东西 / 存下来的视角
    settingsChanged = Signal()      # 快捷键 / 手势轮改了
    kindChanged = Signal()          # 开着的文档换了一种: 零件 / 装配体 / 工程图
    startChanged = Signal()         # 开始页 (刚打开软件时: 选新建哪一种 / 打开最近的文件) 显示 / 收起, 最近文件列表变了
    dialogRequested = Signal(str)   # 要界面打开一个对话框: open / save / export / settings
    contextRequested = Signal(float, float)     # 在视图里点中了东西: 在这个位置 (视图里的像素) 弹出小工具条; 负数 = 收起来
    viewMenuRequested = Signal(str, float, float)   # 视图里右键单击: 在这个位置弹右键菜单 (特征 id; 空 = 零件的菜单)
    appearanceRequested = Signal()  # 打开 "编辑外观"
    progressChanged = Signal()      # 重算做到哪了 (进度条)
    measureChanged = Signal()       # 测量: 开 / 关 / 选的东西变了 / 结果出来了
    languageChanged = Signal()      # 界面语言换了
    treeChanged = Signal()          # 设计树的内容真的变了 (见 StateMixin._refresh_tree)
    treeAboutToChange = Signal()    # 设计树马上要换内容: QML 先记下滚到哪了, 换完滚回去 (换模型 ListView 会跳回顶上)


changed = Signals.changed
formChanged = Signals.formChanged
sketchChanged = Signals.sketchChanged
hoverTextChanged = Signals.hoverTextChanged
notice = Signals.notice
viewChanged = Signals.viewChanged
settingsChanged = Signals.settingsChanged
kindChanged = Signals.kindChanged
startChanged = Signals.startChanged
dialogRequested = Signals.dialogRequested
contextRequested = Signals.contextRequested
viewMenuRequested = Signals.viewMenuRequested
appearanceRequested = Signals.appearanceRequested
progressChanged = Signals.progressChanged
measureChanged = Signals.measureChanged
languageChanged = Signals.languageChanged
treeChanged = Signals.treeChanged
treeAboutToChange = Signals.treeAboutToChange
