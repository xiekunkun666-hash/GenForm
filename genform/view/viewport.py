"""三维视图控件 (QML 里的 Viewport): 显示模型和基准面、转动视角、点选、编辑草图。

操作 (和常见 CAD 接近):
    左键单击      选择面 / 边 / 草图线 / 基准面 (按住 Ctrl 加选或取消; 点空白处清空)
    左键拖动      拉出蓝色的选择框: 从左往右拖 = 整个在框里的才选中; 从右往左拖 = 碰到框的都选中
    中键拖动      旋转视角         (没有中键: Alt + 左键拖动)
    Ctrl + 中键   平移视角         (Shift + 中键也行)
    右键拖动      手势轮: 朝某个方向一划就执行那个方向上的命令 (建模和草图各一套, 内容由控制器给)
    滚轮          朝光标所指的位置缩放
编辑草图时左键交给草图编辑器 (画、选、拖), 其余不变。

界面线程管相机、拾取、选择; 渲染线程只负责把同步过去的数据画出来。只在内容变了的时候重画, 空闲不占显卡。

实现在 genform/view/viewer/ 包里 (viewport 主类 + display / overlays / viewing / mouse 混入类,
renderer 渲染线程, signals 信号, common 常量); 这里只把对外用的名字转出去。
"""
from .viewer.viewport import Viewport
from .viewer.common import _without_faces, _geometry

__all__ = ['Viewport', '_without_faces', '_geometry']
