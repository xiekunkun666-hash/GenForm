"""仿真页背后的状态: 静力分析、风阻估算、装配体 (干涉检查、装配顺序检查)。

算的事都在内核里 (kernel/simulate.py、kernel/assembly.py), 这里只管: 面板上填的东西、把它们交给内核、
把结果变成面板上的几行字和视图里的颜色 / 标注。界面上叫 sim。

装配体可以存成 .gasm 文件 (JSON): 记的是各个零件文件在哪 (相对 .gasm 自己的位置)、各自的位置和转角、装配顺序 —
零件本身的几何不在里面, 还在各自的 .gform / .step 里。

实现在 genform/sim/ 包里 (simulation 主类 + analysis / assembly 混入类, signals 信号,
common 表); 这里只把对外用的名字转出去。
"""
from .sim.simulation import Simulation
from .sim.common import ramp, number, MODES, AXES, QUALITIES

__all__ = ['Simulation', 'ramp', 'number', 'MODES', 'AXES', 'QUALITIES']
