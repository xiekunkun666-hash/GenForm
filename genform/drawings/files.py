"""存 / 取 (.gdrw) 和导出 (PDF / PNG / SVG / DXF), 以及给面板的状态。"""
from __future__ import annotations

import json
import os
from PySide6.QtCore import Property, QMarginsF, QRectF, QSize, QSizeF, Slot
from PySide6.QtGui import QColor, QImage, QPageSize, QPainter, QPdfWriter

from .. import i18n
from .common import _local, number, scale_text, SCALES, SHEETS, TITLE_FIELDS, VIEWS
from .signals import changed


class FileMixin:
    """存取和导出 (工程图的一部分)。"""

    # ---- 存 / 取 ----
    def _part_file(self):
        return self._source or self.app.session.document.path or ''

    @Slot(str)
    def save(self, where):
        path = _local(where) or self.path
        if not path:
            return
        if not path.lower().endswith('.gdrw'):
            path += '.gdrw'
        part = self._part_file()
        if not part:
            self.app.notice.emit('先把零件保存成文件：工程图里记的是零件文件在哪')
            return
        folder = os.path.dirname(os.path.abspath(path))
        try:
            relative = os.path.relpath(part, folder).replace(os.sep, '/')
        except ValueError:                  # 不在同一个盘上: 只能记完整路径
            relative = os.path.abspath(part).replace(os.sep, '/')
        data = {'format': 'genform-drawing', 'version': 1, 'part': relative, 'sheet': self._sheet, 'scale': self._scale,
                'views': self._views, 'offsets': self._offsets, 'hidden': self._hidden, 'auto': self._auto, 'centers': self._centers,
                'dimensions': self._dims, 'title': self._title}
        try:
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False, indent=1)
        except OSError as error:
            self.app.notice.emit(f'存不了：{error}')
            return
        self.path, self.dirty = path, False
        self.app.notice.emit(f'工程图已保存到 {path}')
        self.app.changed.emit()
        self.changed.emit()

    def open(self, path):
        """打开 .gdrw → 成不成。"""
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            if data.get('format') != 'genform-drawing':
                raise ValueError('不是 GenForm 工程图文件')
            part = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), data['part']))
            sheet = data.get('sheet', 'A3')
            if sheet not in SHEETS:
                raise ValueError(f'不认识的图纸 {sheet}')
            names = dict(VIEWS)
            dims = [dim for dim in data.get('dimensions') or [] if dim.get('view') in names and dim.get('kind') in ('linear', 'round')]
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.app.notice.emit(f'打不开这张工程图：{error}')
            return False
        self._ticket += 1
        self._reset()
        self.path, self._source, self._sheet = path, part, sheet
        self._scale = float(data.get('scale') or 0.0)
        self._views = [name for name in data.get('views') or [] if name in names]
        self._offsets = {name: [float(value) for value in offset][:2] for name, offset in (data.get('offsets') or {}).items()
                         if name in names}
        self._hidden, self._auto = bool(data.get('hidden', True)), bool(data.get('auto', True))
        self._centers = bool(data.get('centers', True))
        self._dims = dims
        self._title.update({key: str(value) for key, value in (data.get('title') or {}).items() if key in self._title})
        if not os.path.isfile(part):
            self._error = f'找不到零件文件 {part}'
        else:
            self.project()
        if self.view is not None:
            self.view.fit()
        self._refresh()
        return True

    # ---- 导出 ----
    def _clean(self):
        """导出用的那张图: 不带选中的颜色、标到一半的东西。"""
        kept = self._selected, self._draft, self._mark
        self._selected, self._draft, self._mark, self._composed = -1, None, None, None
        try:
            return self.compose()
        finally:
            self._selected, self._draft, self._mark = kept
            self._composed = None

    @Slot(str)
    def export(self, where):
        """按扩展名导出: .pdf / .svg / .dxf / .png。"""
        path = _local(where)
        if not self._placed and not self._shown():
            self.app.notice.emit('图纸上还没有视图')
            return
        from ..view.sheet import paint_sheet
        sheet = self._clean()
        width, height = sheet['size']
        kind = os.path.splitext(path)[1].lower()
        try:
            if kind == '.pdf':
                writer = QPdfWriter(path)
                writer.setPageSize(QPageSize(QSizeF(width, height), QPageSize.Millimeter))
                writer.setPageMargins(QMarginsF(0, 0, 0, 0))
                writer.setResolution(600)
                writer.setTitle(self._title['name'] or 'GenForm')
                painter = QPainter(writer)
                painter.scale(600 / 25.4, 600 / 25.4)
                paint_sheet(painter, sheet)
                painter.end()
            elif kind == '.svg':
                from PySide6.QtSvg import QSvgGenerator
                generator = QSvgGenerator()
                generator.setFileName(path)
                generator.setSize(QSize(round(width * 96 / 25.4), round(height * 96 / 25.4)))
                generator.setViewBox(QRectF(0, 0, width, height))
                generator.setTitle(self._title['name'] or 'GenForm')
                painter = QPainter(generator)
                paint_sheet(painter, sheet)
                painter.end()
            elif kind == '.png':
                dots = 8.0                  # 一毫米 8 个点 ≈ 200 dpi
                image = QImage(round(width * dots), round(height * dots), QImage.Format_RGB32)
                image.fill(QColor(255, 255, 255))
                painter = QPainter(image)
                painter.scale(dots, dots)
                paint_sheet(painter, sheet)
                painter.end()
                if not image.save(path):
                    raise OSError('写不了这个文件')
            elif kind == '.dxf':
                self._write_dxf(path, sheet)
            else:
                self.app.notice.emit('导出只认 .pdf / .svg / .dxf / .png')
                return
        except OSError as error:
            self.app.notice.emit(f'导出没成：{error}')
            return
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            self.app.notice.emit('导出没成：文件没写出来')
            return
        self.app.notice.emit(f'已导出到 {path}')

    def _write_dxf(self, path, sheet):
        """DXF (R12 的写法, 各家 CAD 都认): 线分三层 — VISIBLE 轮廓、HIDDEN 虚线、DIM 尺寸和图框; 字是 TEXT。y 翻成向上。"""
        height = sheet['size'][1]
        rows = ['0', 'SECTION', '2', 'HEADER', '9', '$INSUNITS', '70', '4', '0', 'ENDSEC',
                '0', 'SECTION', '2', 'TABLES', '0', 'TABLE', '2', 'LTYPE', '70', '2',
                '0', 'LTYPE', '2', 'CONTINUOUS', '70', '0', '3', 'Solid', '72', '65', '73', '0', '40', '0.0',
                '0', 'LTYPE', '2', 'HIDDEN', '70', '0', '3', 'Hidden', '72', '65', '73', '2', '40', '4.5', '49', '3.0', '49', '-1.5',
                '0', 'ENDTAB', '0', 'TABLE', '2', 'LAYER', '70', '3']
        for layer, color, style in (('VISIBLE', 7, 'CONTINUOUS'), ('HIDDEN', 8, 'HIDDEN'), ('DIM', 3, 'CONTINUOUS')):
            rows += ['0', 'LAYER', '2', layer, '70', '0', '62', str(color), '6', style]
        rows += ['0', 'ENDTAB', '0', 'ENDSEC', '0', 'SECTION', '2', 'ENTITIES']

        def segments(layer, points):
            for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
                rows.extend(['0', 'LINE', '8', layer, '10', f'{x0:.4f}', '20', f'{height - y0:.4f}', '11', f'{x1:.4f}',
                             '21', f'{height - y1:.4f}'])
        for name, place in self._placed.items():
            view = self._data['views'][name]
            for layer, lines in (('VISIBLE', view['visible']), ('HIDDEN', view['hidden'] if self._hidden and name != 'iso' else [])):
                for line in lines:
                    segments(layer, [self._to_sheet(place, point) for point in line])
        for kind, points in sheet['lines']:
            segments('VISIBLE' if kind == 'frame' else 'DIM', points)
        for x, y, ux, uy, _ in sheet['arrows']:
            bx, by = x - ux * 3.2, y - uy * 3.2
            rows.extend(['0', 'SOLID', '8', 'DIM', '10', f'{x:.4f}', '20', f'{height - y:.4f}',
                         '11', f'{bx - uy * 0.55:.4f}', '21', f'{height - (by + ux * 0.55):.4f}',
                         '12', f'{bx + uy * 0.55:.4f}', '22', f'{height - (by - ux * 0.55):.4f}',
                         '13', f'{bx + uy * 0.55:.4f}', '23', f'{height - (by - ux * 0.55):.4f}'])
        for item in sheet['texts']:
            x, y = f'{item["x"]:.4f}', f'{height - item["y"]:.4f}'
            rows.extend(['0', 'TEXT', '8', 'DIM', '10', x, '20', y, '40', f'{item["height"]:.3f}', '1', item['text'].replace('Ø', '%%c'),
                         '50', f'{-item.get("angle", 0.0):.3f}', '72', {'l': '0', 'c': '1', 'r': '2'}[item.get('align', 'l')],
                         '11', x, '21', y])
        rows += ['0', 'ENDSEC', '0', 'EOF']
        with open(path, 'w', encoding='utf-8', newline='\r\n') as handle:
            handle.write('\n'.join(rows) + '\n')

    # ---- 给面板的 ----
    @Property('QVariantMap', notify=changed)
    def state(self):
        tr = i18n.tr
        data = self._data
        placed, scale = self._layout() if data else ({}, 1.0)
        part = self._source or self.app.session.document.path
        notes = [tr('手标的尺寸记的是视图里两个点的位置：零件改了以后不会跟着变，要删掉重标'),
                 tr('拖视图可以挪位置；滚轮缩放，拖空白处平移，双击中键放满')]
        if data and not data.get('exact', True):
            notes.insert(0, tr('这个零件的面很多（{} 个），是用网格消隐的：曲面的轮廓是折线，认不出圆，不能点圆标直径').format(data['faces']))
        if self._tool == 'dimension':
            draft = self._draft
            hint = ('点第一个点（线的端点、圆心），或者点一个圆标直径' if draft is None else
                    '点第二个点' if 'b' not in draft else '移动鼠标选标在哪一边，点一下放下')
        else:
            hint = ''
        return {'source': os.path.basename(part) if part else (tr('当前零件（还没保存）') if data else ''),
                'ready': bool(data), 'running': self._running, 'error': tr(self._error) if self._error else '',
                'sheet': self._sheet, 'sheets': list(SHEETS), 'scale': scale_text(scale) if placed else '',
                'scaleChoice': 'auto' if self._scale <= 0 else f'{self._scale:g}',
                'scales': [{'id': 'auto', 'title': tr('自动')}] + [{'id': f'{value:g}', 'title': scale_text(value)} for value in SCALES],
                'views': [{'id': name, 'title': tr(title), 'on': name in self._views} for name, title in VIEWS],
                'hidden': self._hidden, 'auto': self._auto, 'centers': self._centers, 'tool': self._tool, 'hint': tr(hint),
                'selected': self._selected >= 0, 'dimensions': len(self._dims), 'moved': bool(self._offsets),
                'size': ' × '.join(number(value) for value in data['size']) + ' mm' if data else '',
                'title': [{'id': key, 'label': tr(label), 'value': self._title[key]} for key, label in TITLE_FIELDS],
                'notes': notes}
