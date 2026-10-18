# -*- coding: utf-8 -*-
"""工程图的图纸: 把 drawing.py 排好的一张图 (线、字、箭头) 画出来。

同一个画法 (paint_sheet) 用三次: 界面上的图纸 (SheetView)、导出 PDF / SVG / PNG。坐标都是图纸上的毫米, 左上角是原点, y 向下。
SheetView 自己只管看图: 滚轮缩放、拖动平移; 点在哪、拖了什么都转成图纸上的毫米交给 drawing.py。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Property, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF, QTransform
from PySide6.QtQuick import QQuickPaintedItem

FONT = 'Microsoft YaHei UI'
# 线型: 名字 → (线宽 mm, 虚线的一段一段 (mm) 或 None, 颜色)
INK, BLUE = QColor(20, 20, 24), QColor(46, 125, 235)
STYLES = {
    'frame': (0.7, None, INK), 'visible': (0.5, None, INK), 'hidden': (0.25, (3.0, 1.5), INK), 'thin': (0.18, None, INK),
    'center': (0.18, (8.0, 1.5, 1.0, 1.5), INK), 'select': (0.4, None, BLUE), 'draft': (0.3, None, BLUE),
}
ARROW_LENGTH, ARROW_HALF = 3.2, 0.55        # 箭头: 长, 半宽 (mm)


def _pen(kind, thinnest):
    width, dashes, color = STYLES[kind]
    width = max(width, thinnest * (1.4 if kind in ('visible', 'frame') else 1.0))     # 屏幕上缩得很小时线也不能细到看不见
    pen = QPen(color, width, Qt.SolidLine, Qt.FlatCap if dashes else Qt.RoundCap, Qt.RoundJoin)
    if dashes:
        pen.setDashPattern([value / width for value in dashes])
    return pen


def paint_sheet(painter, sheet, thinnest=0.0):
    """sheet: drawing.Drawing.compose() 给的那张图。thinnest: 线最细画多宽 (mm); 导出时是 0, 屏幕上是一个像素那么宽。"""
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(Qt.NoBrush)
    for name, transform, visible, hidden in sheet['paths']:            # 各个视图投影出来的线 (量大, 是事先拼好的路径)
        if hidden is not None:
            painter.setPen(_pen('hidden', thinnest))
            painter.drawPath(transform.map(hidden))
        painter.setPen(_pen('visible', thinnest))
        painter.drawPath(transform.map(visible))
    for kind, points in sheet['lines']:
        painter.setPen(_pen(kind, thinnest))
        painter.drawPolyline(QPolygonF([QPointF(float(x), float(y)) for x, y in points]))
    painter.setPen(Qt.NoPen)
    for x, y, ux, uy, kind in sheet['arrows']:
        painter.setBrush(STYLES[kind][2])
        bx, by = x - ux * ARROW_LENGTH, y - uy * ARROW_LENGTH
        painter.drawPolygon(QPolygonF([QPointF(x, y), QPointF(bx - uy * ARROW_HALF, by + ux * ARROW_HALF),
                                       QPointF(bx + uy * ARROW_HALF, by - ux * ARROW_HALF)]))
    font = QFont(FONT)
    font.setPixelSize(100)                  # 字按 100 个单位高来排, 再整体缩到要的毫米数: 字号只能是整数, 直接用毫米太粗
    painter.setFont(font)
    for item in sheet['texts']:
        painter.save()
        painter.translate(item['x'], item['y'])
        if item.get('angle'):
            painter.rotate(item['angle'])
        factor = item['height'] / 72.0      # 100 个单位的字, 大写字母和数字大约 72 高
        painter.scale(factor, factor)
        painter.setPen(STYLES[item.get('kind', 'thin')][2])
        width = painter.fontMetrics().horizontalAdvance(item['text'])
        left = {'l': 0.0, 'c': -width / 2.0, 'r': -float(width)}[item.get('align', 'l')]
        painter.drawText(QPointF(left, 0.0), item['text'])
        painter.restore()
    for x, y in sheet.get('marks', ()):     # 标尺寸时吸住的点: 一个小圈
        painter.setPen(_pen('draft', thinnest))
        painter.setBrush(Qt.NoBrush)
        radius = max(1.2, thinnest * 5)
        painter.drawEllipse(QPointF(x, y), radius, radius)


class SheetView(QQuickPaintedItem):
    """界面上的图纸。owner 是 drawing.Drawing (bootstrap 接上)。"""
    darkChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.owner = None
        self._dark = True
        self._zoom = 0.0                    # 一毫米画多少像素; 0 = 还没定, 下次画的时候取 "整张图纸正好放下"
        self._origin = QPointF(0, 0)        # 图纸左上角在控件里的位置 (像素)
        self._fitted = True                 # 用户还没自己缩放 / 平移过: 控件大小变了就重新放满
        self._press = None                  # 按下时: (按键, 位置, 有没有拖起来, 拖的是哪个视图)
        self.setAcceptedMouseButtons(Qt.LeftButton | Qt.MiddleButton | Qt.RightButton)
        self.setAcceptHoverEvents(True)
        self.setAntialiasing(True)
        self.setRenderTarget(QQuickPaintedItem.FramebufferObject)
        self.widthChanged.connect(self._resized)
        self.heightChanged.connect(self._resized)

    def _get_dark(self):
        return self._dark

    def _set_dark(self, value):
        if value != self._dark:
            self._dark = value
            self.darkChanged.emit()
            self.update()

    dark = Property(bool, _get_dark, _set_dark, notify=darkChanged)

    # ---- 取景 ----
    def fit(self):
        self._fitted = True
        self._zoom = 0.0
        self.update()

    def _resized(self):
        if self._fitted:
            self._zoom = 0.0
        self.update()

    def _frame(self, size):
        if self._zoom <= 0 and self.width() > 40 and self.height() > 40:
            self._zoom = min((self.width() - 48) / size[0], (self.height() - 48) / size[1])
            self._origin = QPointF((self.width() - size[0] * self._zoom) / 2, (self.height() - size[1] * self._zoom) / 2)
        return max(self._zoom, 1e-6)

    def _to_sheet(self, position):
        zoom = max(self._zoom, 1e-6)
        return (position.x() - self._origin.x()) / zoom, (position.y() - self._origin.y()) / zoom

    @property
    def pixel(self):
        """一个像素是图纸上的多少毫米。"""
        return 1.0 / max(self._zoom, 1e-6)

    # ---- 画 ----
    def paint(self, painter):
        painter.fillRect(QRectF(0, 0, self.width(), self.height()), QColor(30, 31, 34) if self._dark else QColor(214, 219, 227))
        if self.owner is None:
            return
        sheet = self.owner.compose()
        width, height = sheet['size']
        zoom = self._frame(sheet['size'])
        painter.translate(self._origin)
        painter.scale(zoom, zoom)
        painter.fillRect(QRectF(1.2, 1.2, width, height), QColor(0, 0, 0, 70))        # 纸的影子
        painter.fillRect(QRectF(0, 0, width, height), QColor(255, 255, 255))
        paint_sheet(painter, sheet, 1.0 / zoom)

    # ---- 鼠标 ----
    def wheelEvent(self, event):
        step = event.angleDelta().y()
        if not step or self._zoom <= 0:
            return
        factor = 1.0015 ** step
        zoom = min(max(self._zoom * factor, 0.05), 400.0)
        at = event.position()
        self._origin = QPointF(at.x() - (at.x() - self._origin.x()) * zoom / self._zoom,
                               at.y() - (at.y() - self._origin.y()) * zoom / self._zoom)
        self._zoom, self._fitted = zoom, False
        self.update()
        event.accept()

    def mousePressEvent(self, event):
        self.forceActiveFocus()
        grabbed = None
        if event.button() == Qt.LeftButton and self.owner is not None:
            grabbed = self.owner.grab_at(*self._to_sheet(event.position()))
        self._press = [event.button(), event.position(), False, grabbed]
        event.accept()

    def mouseMoveEvent(self, event):
        if self._press is None:
            return
        button, last, moved, grabbed = self._press
        delta = event.position() - last
        if not moved and abs(delta.x()) + abs(delta.y()) < 4:
            return
        self._press[1], self._press[2] = event.position(), True
        if grabbed is not None and self.owner is not None:      # 拖一个视图: 在图纸上挪它
            self.owner.drag(grabbed, delta.x() * self.pixel, delta.y() * self.pixel)
        else:                                                   # 别的都是平移图纸
            self._origin = self._origin + delta
            self._fitted = False
            self.update()

    def mouseReleaseEvent(self, event):
        press, self._press = self._press, None
        if press is None or self.owner is None:
            return
        if press[2]:
            if press[3] is not None:
                self.owner.drag_done()
        elif press[0] == Qt.LeftButton:
            self.owner.click(*self._to_sheet(event.position()), self.pixel)
        elif press[0] == Qt.RightButton:
            self.owner.cancel()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self.fit()

    def hoverMoveEvent(self, event):
        if self.owner is not None:
            self.owner.hover(*self._to_sheet(event.position()), self.pixel)
