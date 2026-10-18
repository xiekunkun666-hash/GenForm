"""排版: 视图摆在哪、图纸和视图坐标换算、自动标注尺寸, 合成图纸上要画的东西。"""
from __future__ import annotations

import math
import numpy as np
from PySide6.QtGui import QTransform

from .. import i18n
from .common import GAP, MARGIN, number, OFFSET, scale_text, SCALES, SHEETS, TEXT, TITLE, VIEWS


class LayoutMixin:
    """排版 (工程图的一部分)。"""

    # ---- 排版 ----
    def _shown(self):
        if not self._data:
            return []
        return [name for name, _ in VIEWS if name in self._views and name in self._data['views']]

    def _grid(self, scale, shown):
        """按这个比例排: → (各视图的中心和比例, 排不排得下)。"""
        width, height = SHEETS[self._sheet]
        boxes = {name: self._data['views'][name]['box'] for name in shown}
        size = {name: (box[2] - box[0], box[3] - box[1]) for name, box in boxes.items()}

        def extent(names, axis):
            return max([size[name][axis] * scale for name in names if name in size] or [0.0])
        column0, row0 = extent(('front', 'top'), 0), extent(('front', 'left'), 1)
        column1, row1 = extent(('left',), 0), extent(('top',), 1)
        if 'iso' in size:                   # 轴测图占右下那一格: 这一格至少留这么大
            column1, row1 = max(column1, 70.0), max(row1, 55.0 + TITLE[1])
        if not column0:                     # 没有主视图也没有俯视图: 右边那一列顶上来
            column0, column1 = column1, 0.0
        if not row0:
            row0, row1 = row1, 0.0
        total = (column0 + (GAP + column1 if column1 else 0.0), row0 + (GAP + row1 if row1 else 0.0))
        room = (width - 2 * MARGIN - 36.0, height - 2 * MARGIN - 30.0)
        left, top = (width - total[0]) / 2 + 6.0, (height - total[1]) / 2
        x0, x1 = left + column0 / 2, left + column0 + GAP + column1 / 2
        y0, y1 = top + row0 / 2, top + row0 + GAP + row1 / 2
        if not column1:
            x1 = x0
        if not row1:
            y1 = y0
        placed = {}
        for name, (cx, cy) in (('front', (x0, y0)), ('top', (x0, y1)), ('left', (x1, y0))):
            if name in size:
                placed[name] = [cx, cy, scale]
        if 'iso' in size:
            cell = (max(column1, 70.0) if column1 else column0, (row1 if row1 else row0) - (TITLE[1] if row1 else 0.0))
            own = min(scale, cell[0] / max(size['iso'][0], 1e-9), max(cell[1], 30.0) / max(size['iso'][1], 1e-9))
            placed['iso'] = [x1 if column1 else x0, (y1 - TITLE[1] / 2) if row1 else y0, own]
        return placed, total[0] <= room[0] and total[1] <= room[1]

    def _layout(self):
        shown = self._shown()
        if not shown:
            return {}, 1.0
        if self._scale > 0:
            scale = self._scale
            placed, _ = self._grid(scale, shown)
        else:
            for scale in SCALES:            # 自动: 排得下的最大的那个标准比例
                placed, fits = self._grid(scale, shown)
                if fits:
                    break
        result = {}
        for name, (cx, cy, own) in placed.items():
            box = self._data['views'][name]['box']
            dx, dy = self._offsets.get(name, (0.0, 0.0))
            result[name] = (cx + dx, cy + dy, own, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        return result, scale

    @staticmethod
    def _to_sheet(place, point):
        cx, cy, scale, bx, by = place
        return cx + (point[0] - bx) * scale, cy - (point[1] - by) * scale

    @staticmethod
    def _to_view(place, x, y):
        cx, cy, scale, bx, by = place
        return bx + (x - cx) / scale, by - (y - cy) / scale

    def _linear(self, out, place, dim, kind='thin'):
        """一个线性尺寸 (视图坐标里的 a、b 两点) → 界线、尺寸线、箭头、数字。返回数字的位置。"""
        a, b = self._to_sheet(place, dim['a']), self._to_sheet(place, dim['b'])
        mode = dim['mode']
        if mode == 'h':
            level = self._to_sheet(place, (0.0, dim['at']))[1]
            first, second = (a[0], level), (b[0], level)
            value = abs(dim['b'][0] - dim['a'][0])
        elif mode == 'v':
            level = self._to_sheet(place, (dim['at'], 0.0))[0]
            first, second = (level, a[1]), (level, b[1])
            value = abs(dim['b'][1] - dim['a'][1])
        else:
            along = np.array([b[0] - a[0], b[1] - a[1]])
            length = float(np.hypot(*along)) or 1.0
            normal = np.array([-along[1], along[0]]) / length * dim['at'] * place[2]
            first, second = (a[0] + normal[0], a[1] + normal[1]), (b[0] + normal[0], b[1] + normal[1])
            value = math.hypot(dim['b'][0] - dim['a'][0], dim['b'][1] - dim['a'][1])
        for start, end in ((a, first), (b, second)):          # 界线: 离图形留 1 mm, 越过尺寸线 2 mm
            reach = math.hypot(end[0] - start[0], end[1] - start[1])
            if reach > 1e-6:
                ux, uy = (end[0] - start[0]) / reach, (end[1] - start[1]) / reach
                out['lines'].append((kind, [(start[0] + ux * min(1.0, reach), start[1] + uy * min(1.0, reach)),
                                            (end[0] + ux * 2.0, end[1] + uy * 2.0)]))
        span = math.hypot(second[0] - first[0], second[1] - first[1])
        if span < 1e-6:
            return first
        ux, uy = (second[0] - first[0]) / span, (second[1] - first[1]) / span
        if span >= 9.0:                     # 够长: 箭头在里面朝外
            out['lines'].append((kind, [first, second]))
            out['arrows'] += [(first[0], first[1], -ux, -uy, kind), (second[0], second[1], ux, uy, kind)]
        else:                               # 太短: 箭头在外面朝里
            out['lines'].append((kind, [(first[0] - ux * 6, first[1] - uy * 6), (second[0] + ux * 6, second[1] + uy * 6)]))
            out['arrows'] += [(first[0], first[1], ux, uy, kind), (second[0], second[1], -ux, -uy, kind)]
        if ux < -1e-9 or (abs(ux) <= 1e-9 and uy > 0):      # 字要正着读: 朝右, 竖着的从下往上
            ux, uy = -ux, -uy
        angle = math.degrees(math.atan2(uy, ux))
        middle = ((first[0] + second[0]) / 2 + uy * 1.2, (first[1] + second[1]) / 2 - ux * 1.2)
        out['texts'].append({'x': middle[0], 'y': middle[1], 'text': number(value), 'height': TEXT, 'align': 'c', 'angle': angle,
                             'kind': kind})
        return middle

    def _round(self, out, place, dim, kind='thin'):
        """直径 / 半径: 从圆上引一条线出来, 末端折一小段横线, 上面写 Ø / R。"""
        center, at = self._to_sheet(place, dim['c']), self._to_sheet(place, dim['at'])
        reach = math.hypot(at[0] - center[0], at[1] - center[1]) or 1.0
        ux, uy = (at[0] - center[0]) / reach, (at[1] - center[1]) / reach
        radius = dim['r'] * place[2]
        edge = (center[0] + ux * radius, center[1] + uy * radius)
        if reach < radius + 5.0:
            at = (center[0] + ux * (radius + 8.0), center[1] + uy * (radius + 8.0))
        side = 1.0 if ux >= 0 else -1.0
        text = ('Ø' + number(dim['r'] * 2)) if dim.get('full', True) else ('R' + number(dim['r']))
        shelf = (at[0] + side * (len(text) * TEXT * 0.72 + 2.0), at[1])
        out['lines'].append((kind, [edge, at, shelf]))
        out['arrows'].append((edge[0], edge[1], -ux, -uy, kind))
        out['texts'].append({'x': (at[0] + shelf[0]) / 2, 'y': at[1] - 1.2, 'text': text, 'height': TEXT, 'align': 'c', 'kind': kind})
        return (at[0] + shelf[0]) / 2, at[1] - 1.2

    def _dimension(self, out, place, dim, kind='thin'):
        return (self._round if dim['kind'] == 'round' else self._linear)(out, place, dim, kind)

    def _automatic(self, placed):
        """长、宽、高各标一次, 标在第一个看得出它的视图上。"""
        done, dims = set(), []
        for name, across, up in (('front', 'x', 'z'), ('top', 'x', 'y'), ('left', 'y', 'z')):
            if name not in placed:
                continue
            box, gap = self._data['views'][name]['box'], OFFSET / placed[name][2]
            if across not in done and box[2] - box[0] > 1e-6:
                done.add(across)
                dims.append({'view': name, 'kind': 'linear', 'mode': 'h', 'a': (box[0], box[1]), 'b': (box[2], box[1]), 'at': box[1] - gap})
            if up not in done and box[3] - box[1] > 1e-6:
                done.add(up)
                dims.append({'view': name, 'kind': 'linear', 'mode': 'v', 'a': (box[0], box[1]), 'b': (box[0], box[3]), 'at': box[0] - gap})
        return dims

    def compose(self):
        """排成一张图: {'size', 'paths', 'lines', 'arrows', 'texts', 'marks'} (见 view/sheet.paint_sheet)。"""
        if self._composed is not None:
            return self._composed
        tr = i18n.tr
        width, height = SHEETS[self._sheet]
        out = {'size': (width, height), 'paths': [], 'lines': [], 'arrows': [], 'texts': [], 'marks': []}
        out['lines'].append(('frame', [(MARGIN, MARGIN), (width - MARGIN, MARGIN), (width - MARGIN, height - MARGIN),
                                       (MARGIN, height - MARGIN), (MARGIN, MARGIN)]))
        placed, scale = self._layout()
        self._placed = placed
        for name, place in placed.items():
            cx, cy, own, bx, by = place
            transform = QTransform().translate(cx, cy).scale(own, own).translate(-bx, by)
            visible, hidden = self._paths[name]
            out['paths'].append((name, transform, visible, hidden if self._hidden and name != 'iso' else None))
            if self._centers and name != 'iso':
                for x, y, radius, full in self._data['views'][name]['circles'][:300]:
                    if full:
                        reach = radius + 2.5 / own
                        out['lines'].append(('center', [self._to_sheet(place, (x - reach, y)), self._to_sheet(place, (x + reach, y))]))
                        out['lines'].append(('center', [self._to_sheet(place, (x, y - reach)), self._to_sheet(place, (x, y + reach))]))
        if self._auto:
            for dim in self._automatic(placed):
                self._dimension(out, placed[dim['view']], dim)
        self._handles = []
        for index, dim in enumerate(self._dims):
            if dim['view'] in placed:
                spot = self._dimension(out, placed[dim['view']], dim, 'select' if index == self._selected else 'thin')
                self._handles.append((index, spot[0], spot[1]))
        if self._draft is not None and self._draft['view'] in placed:
            place, draft = placed[self._draft['view']], self._draft
            if 'mode' in draft:
                self._dimension(out, place, draft, 'draft')
            elif self._mark is not None:
                out['lines'].append(('draft', [self._to_sheet(place, draft['a']), self._mark]))
            out['marks'].append(self._to_sheet(place, draft['a']))
            if 'b' in draft:
                out['marks'].append(self._to_sheet(place, draft['b']))
        if self._mark is not None and self._tool:
            out['marks'].append(self._mark)
        # 标题栏: 右下角贴着图框
        x0, y0 = width - MARGIN - TITLE[0], height - MARGIN - TITLE[1]
        row = TITLE[1] / 4
        out['lines'].append(('frame', [(x0, height - MARGIN), (x0, y0), (width - MARGIN, y0)]))
        for start, end in (((x0 + 70, y0), (x0 + 70, y0 + TITLE[1])), ((x0, y0 + 2 * row), (x0 + 70, y0 + 2 * row)),
                           ((x0, y0 + 3 * row), (x0 + 70, y0 + 3 * row)), ((x0 + 70, y0 + row), (x0 + 140, y0 + row)),
                           ((x0 + 70, y0 + 2 * row), (x0 + 140, y0 + 2 * row)), ((x0 + 70, y0 + 3 * row), (x0 + 140, y0 + 3 * row)),
                           ((x0 + 16, y0 + 2 * row), (x0 + 16, y0 + TITLE[1])), ((x0 + 86, y0), (x0 + 86, y0 + 3 * row)),
                           ((x0 + 105, y0), (x0 + 105, y0 + row)), ((x0 + 121, y0), (x0 + 121, y0 + row))):
            out['lines'].append(('thin', [start, end]))

        def write(x, y, text, size=3.0, align='l'):
            if text:
                out['texts'].append({'x': x0 + x, 'y': y0 + y, 'text': str(text), 'height': size, 'align': align})
        title = self._title
        write(35, row + 2.2, title['name'] or tr('未命名零件'), 5.0, 'c')
        for line, (label, value) in enumerate((('材料', title['material']), ('图号', title['number']))):
            write(2, (line + 3) * row - 2.5, tr(label))
            write(18, (line + 3) * row - 2.5, value)
        write(72, row - 2.5, tr('比例'))
        write(95.5, row - 2.5, scale_text(scale) if placed else '', 3.0, 'c')
        write(107, row - 2.5, tr('图纸'))
        write(130.5, row - 2.5, self._sheet, 3.0, 'c')
        for line, (label, value) in enumerate((('设计', title['designer']), ('日期', title['date']))):
            write(72, (line + 2) * row - 2.5, tr(label))
            write(88, (line + 2) * row - 2.5, value)
        write(105, 4 * row - 2.5, tr('第一角画法　单位 mm'), 2.6, 'c')
        if not placed:
            hint = '正在投影…' if self._running else (self._error or '还没有零件：在左边点“选择零件…”')
            out['texts'].append({'x': width / 2, 'y': height / 2, 'text': tr(hint), 'height': 6.0, 'align': 'c'})
        self._composed = out
        return out
