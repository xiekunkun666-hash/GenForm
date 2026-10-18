"""工程图: 一个零件的几个投影视图排在一张图纸上, 加尺寸和标题栏, 导出 PDF / SVG / DXF / PNG。界面上叫 drawing。

投影在内核里算 (kernel/drawing.py); 这里管: 图纸多大、比例多少、视图摆在哪、尺寸标在哪, 把它们排成一张图 (compose),
交给 view/sheet.py 去画。图纸上的坐标是毫米, 左上角是原点, y 向下; 视图自己的坐标是零件的毫米, y 向上。

存成 .gdrw (JSON): 零件文件在哪 (相对 .gdrw 自己)、图纸、比例、显示哪些视图、各视图挪了多少、手标的尺寸、标题栏里填的字。
零件的几何不在里面。手标的尺寸记的是视图里的两个点的坐标: 零件改了以后它们不会跟着走, 要删掉重标。

实现在 genform/drawings/ 包里 (drawing 主类 + panel / layout / mouse / files 混入类,
signals 信号, common 表); 这里只把对外用的名字转出去。
"""
from .drawings.drawing import Drawing
from .drawings.common import scale_text, number, SHEETS, SCALES, VIEWS

__all__ = ['Drawing', 'scale_text', 'number', 'SHEETS', 'SCALES', 'VIEWS']
