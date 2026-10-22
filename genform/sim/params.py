# -*- coding: utf-8 -*-
"""装配体的全局变量和配合 (仿真页的一部分)。

全局变量: .gasm 里的 params = {名字: 数 或 "=表达式"} (按先后定义, 只能用前面的)。改了以后:
  · 各个零件文件里 "全局变量" 特征中同名的变量改成这个值 (写回零件文件; 零件里用 =表达式 引用它的特征跟着变);
  · 零件位置里写成 "=表达式" 的 (比如 Z = "=H_stack+0.5") 重新算。
配合: .gasm 里的 mates = [{'kind', 'part', 'to', 'axis', 'value'}...], 按顺序一条条摆 (不是联立求解):
  · coaxial 同轴: part 在另外两个方向上的位置 = to 的 (两个零件原点在同一根平行于 axis 的线上);
  · offset 距离: part 沿 axis 的位置 = to 的 + value (value 可以写 "=表达式")。
配合摆好的方向会盖掉手填的值 (面板上那一格显示成配合给的数)。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Property, Slot

from ..sketchgeo.base import evaluate
from .signals import changed

MATE_KINDS = {'coaxial': '同轴', 'offset': '距离'}
AXES = 'XYZ'


def _number_or_formula(text):
    """面板里填的 → 数 或 "=表达式" (字符串); 填不出来 ValueError。"""
    text = str(text).strip()
    if text.startswith('='):
        return text
    return float(text)


class ParamsMixin:
    """装配体的全局变量 + 配合。"""

    def _params_init(self):
        self._params = {}               # 名字 → 数 或 "=表达式"
        self._mates = []                # [{'kind', 'part', 'to', 'axis', 'value'}...]
        self._param_error = ''

    # ---- 文件 ----
    def _params_from_file(self, data, count):
        params = data.get('params') if isinstance(data.get('params'), dict) else {}
        self._params = {str(name): value for name, value in params.items() if str(name).isidentifier()}
        self._mates = []
        for mate in data.get('mates') or []:
            try:
                row = {'kind': str(mate['kind']), 'part': int(mate['part']), 'to': int(mate['to']),
                       'axis': str(mate.get('axis', 'Z')).upper(), 'value': mate.get('value', 0.0)}
            except (KeyError, TypeError, ValueError):
                continue
            if row['kind'] in MATE_KINDS and row['axis'] in AXES and 0 <= row['part'] < count and 0 <= row['to'] < count \
                    and row['part'] != row['to']:
                self._mates.append(row)

    def _params_to_file(self, data):
        if self._params:
            data['params'] = dict(self._params)
        if self._mates:
            data['mates'] = [dict(mate) for mate in self._mates]

    @staticmethod
    def _place_from_row(row, field):
        """.gasm 里一行的 move / turn → (数 [3], 表达式 [3] (没有的是 None))。"""
        values, formulas = [0.0, 0.0, 0.0], [None, None, None]
        for axis, value in enumerate(list(row.get(field) or (0, 0, 0))[:3]):
            if isinstance(value, str) and value.strip().startswith('='):
                formulas[axis] = value.strip()
            else:
                values[axis] = float(value)
        return values, formulas

    @staticmethod
    def _place_to_row(part, field):
        formulas = (part.get('formula') or {}).get(field) or [None, None, None]
        return [formula if formula else value for value, formula in zip(part[field], formulas)]

    # ---- 算 ----
    def _param_values(self):
        """全局变量 → {名字: 数}; 算不出来的跳过, 记在 _param_error。"""
        known, problems = {}, []
        for name, text in self._params.items():
            try:
                known[name] = evaluate(text.strip()[1:], **known) if isinstance(text, str) and text.strip().startswith('=') \
                    else float(text)
            except (ValueError, TypeError) as error:
                problems.append(f'{name}：{error}')
        self._param_error = '；'.join(problems)
        return known

    def _apply_layout(self):
        """位置里的表达式重新算, 再按顺序摆配合。返回有没有零件挪了。"""
        known = self._param_values()
        problems, moved = [], False

        def value_of(text, where):
            try:
                return evaluate(text.strip()[1:], **known) if isinstance(text, str) else float(text)
            except (ValueError, TypeError) as error:
                problems.append(f'{where}：{error}')
                return None

        for part in self._parts:
            for field, formulas in (part.get('formula') or {}).items():
                for axis, formula in enumerate(formulas or ()):
                    if formula:
                        value = value_of(formula, f'{part["name"]} 的{"位置" if field == "move" else "转角"} {AXES[axis]}')
                        if value is not None and abs(part[field][axis] - value) > 1e-9:
                            part[field][axis], moved = value, True
        for mate in self._mates:
            if not (0 <= mate['part'] < len(self._parts) and 0 <= mate['to'] < len(self._parts)):
                continue
            part, base, axis = self._parts[mate['part']], self._parts[mate['to']], AXES.index(mate['axis'])
            if mate['kind'] == 'coaxial':
                targets = {other: base['move'][other] for other in range(3) if other != axis}
            else:
                gap = value_of(mate['value'], f'配合 {part["name"]} → {base["name"]}')
                targets = {axis: base['move'][axis] + gap} if gap is not None else {}
            for other, value in targets.items():
                if abs(part['move'][other] - value) > 1e-9:
                    part['move'][other], moved = float(value), True
        if problems:
            self._param_error = '；'.join(filter(None, [self._param_error] + problems))
        return moved

    def _push_params(self):
        """全局变量写进各个零件文件里同名的变量 (全局变量特征) → 改了几个文件。"""
        known = self._param_values()
        if not known:
            return 0
        touched = 0
        for part in self._parts:
            path = part.get('path') or ''
            if not path.lower().endswith('.gform'):
                continue
            try:
                with open(path, encoding='utf-8') as handle:
                    doc = json.load(handle)
            except (OSError, ValueError):
                continue
            changed_here = False
            for feature in doc.get('features') or []:
                if feature.get('type') != 'variables':
                    continue
                values = (feature.get('params') or {}).get('values') or {}
                for name in values:
                    if name in known and values[name] != known[name]:
                        values[name] = known[name]
                        changed_here = True
            if changed_here:
                try:
                    with open(path, 'w', encoding='utf-8') as handle:
                        json.dump(doc, handle, ensure_ascii=False, indent=1)
                    touched += 1
                except OSError as error:
                    self.app.notice.emit(f'改不了 {path}：{error}')
        return touched

    def _mates_renumber(self, mapping):
        kept = []
        for mate in self._mates:
            if mate['part'] in mapping and mate['to'] in mapping:
                kept.append(dict(mate, part=mapping[mate['part']], to=mapping[mate['to']]))
        self._mates = kept

    def _mated_axes(self, index):
        """这个零件哪几个平移方向是配合定的 (面板上那格不让改)。"""
        fixed = set()
        for mate in self._mates:
            if mate['part'] == index:
                axis = AXES.index(mate['axis'])
                fixed |= {other for other in range(3) if other != axis} if mate['kind'] == 'coaxial' else {axis}
        return fixed

    # ---- 界面 ----
    @Property('QVariantList', notify=changed)
    def params(self):
        """[{'name', 'text' 填的, 'value' 算出来的}...]"""
        known = self._param_values()
        return [{'name': name, 'text': text if isinstance(text, str) else f'{text:g}',
                 'value': f'{known[name]:g}' if name in known else '?'} for name, text in self._params.items()]

    @Property(str, notify=changed)
    def paramError(self):
        return self._param_error

    @Property('QVariantList', notify=changed)
    def mates(self):
        """[{'index', 'kind', 'title', 'part', 'to', 'partName', 'toName', 'axis', 'value'}...]"""
        names = [part['name'] for part in self._parts]
        return [{'index': number, 'kind': mate['kind'], 'title': MATE_KINDS[mate['kind']], 'part': mate['part'], 'to': mate['to'],
                 'partName': names[mate['part']] if mate['part'] < len(names) else '?',
                 'toName': names[mate['to']] if mate['to'] < len(names) else '?', 'axis': mate['axis'],
                 'value': mate['value'] if isinstance(mate['value'], str) else f'{float(mate["value"]):g}'}
                for number, mate in enumerate(self._mates)]

    @Slot(str, str)
    def setParam(self, name, text):
        """加 / 改一个全局变量 (text 空 = 删掉)。改完写进零件文件, 位置和配合重新摆。"""
        name = name.strip()
        if not name.isidentifier():
            self.app.notice.emit('变量名只能用字母、数字、下划线，不能数字开头')
            return
        if not str(text).strip():
            self._params.pop(name, None)
        else:
            try:
                self._params[name] = _number_or_formula(text)
            except ValueError:
                self.app.notice.emit('值要填数字，或者 =表达式（比如 =D/2）')
                self.changed.emit()
                return
        touched = self._push_params()
        if touched:
            self.app.notice.emit(f'全局变量写进了 {touched} 个零件文件')
        self._parts_changed()

    @Slot(int, int, str, str)
    def addMate(self, part, to, kind, axis):
        """part 配合到 to 上。距离的初始值 = 现在两个件沿这根轴差多少 (加上以后先不动)。"""
        if kind not in MATE_KINDS or axis not in AXES or part == to or not (0 <= part < len(self._parts)) \
                or not (0 <= to < len(self._parts)):
            return
        index = AXES.index(axis)
        gap = round(self._parts[part]['move'][index] - self._parts[to]['move'][index], 6)
        self._mates.append({'kind': kind, 'part': part, 'to': to, 'axis': axis, 'value': gap})
        self._parts_changed()

    @Slot(int, str, str)
    def setMateField(self, number, field, text):
        """改一条配合: field = value / axis / kind / to / delete。"""
        if not 0 <= number < len(self._mates):
            return
        mate = self._mates[number]
        try:
            if field == 'delete':
                del self._mates[number]
            elif field == 'value':
                mate['value'] = _number_or_formula(text)
            elif field == 'axis' and text.upper() in AXES:
                mate['axis'] = text.upper()
            elif field == 'kind' and text in MATE_KINDS:
                mate['kind'] = text
            elif field == 'to' and 0 <= int(text) < len(self._parts) and int(text) != mate['part']:
                mate['to'] = int(text)
            else:
                return
        except ValueError:
            self.app.notice.emit('距离要填数字，或者 =表达式')
            self.changed.emit()
            return
        self._parts_changed()
