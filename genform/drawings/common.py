"""工程图共用的表 (图纸、比例、视图、边距) 和数字的写法。"""
from __future__ import annotations

from PySide6.QtCore import QUrl


SHEETS = {'A4': (297.0, 210.0), 'A3': (420.0, 297.0), 'A2': (594.0, 420.0), 'A1': (841.0, 594.0)}


SCALES = [10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001]


VIEWS = [('front', '主视图'), ('top', '俯视图'), ('left', '左视图'), ('iso', '轴测图')]


MARGIN = 10.0               # 图框离纸边


GAP = 34.0                  # 视图之间留的空 (放尺寸)


TITLE = (140.0, 32.0)       # 标题栏: 宽, 高


TEXT = 3.5                  # 尺寸数字的高


OFFSET = 10.0               # 自动标的总体尺寸离视图多远


TITLE_FIELDS = [('name', '名称'), ('number', '图号'), ('material', '材料'), ('designer', '设计'), ('date', '日期')]


def number(value):
    text = f'{value:.2f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def scale_text(scale):
    return f'{scale:g}:1' if scale >= 1 else f'1:{1 / scale:g}'


def _local(where):
    text = str(where)
    return QUrl(text).toLocalFile() if text.startswith('file:') else text
