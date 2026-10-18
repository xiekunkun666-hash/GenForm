"""静力分析 (选面、力、网格质量、跑) 和风阻估算, 以及给面板的状态。"""
from __future__ import annotations

from PySide6.QtCore import Property, Slot

from .. import i18n, materials
from .common import AXES, number, QUALITIES
from .signals import changed


class AnalysisMixin:
    """静力和风阻 (仿真页的一部分)。"""

    # ---- 静力分析 ----
    @Slot(str)
    def takeFaces(self, role):
        """把视图里现在选着的面记成固定面 (fixed) 或受力面 (loaded)。"""
        if role not in ('fixed', 'loaded'):
            return
        app = self.app
        faces = [int(face) for face in app.session.selection.get('faces', [])]
        if not faces:
            app.notice.emit('先在视图里点选面（按住 Ctrl 可以多选），再点这个按钮')
            return
        other = 'loaded' if role == 'fixed' else 'fixed'
        self._static[role] = faces
        self._static[other] = [face for face in self._static[other] if face not in faces]
        self._static.update(result=None, error='')
        app.session.selection.update(faces=[], edges=[], plane=None, feature=None)
        app._push_selection()
        self._ticket += 1
        self._running = ''
        self._paint()
        self.changed.emit()

    @Slot(str)
    def showFaces(self, role):
        """在视图里把记着的固定面 / 受力面亮出来看一眼。"""
        if role in ('fixed', 'loaded'):
            self.app.session.selection.update(faces=list(self._static[role]), edges=[], plane=None, feature=None)
            self.app._push_selection()

    @Slot(int, str)
    def setForce(self, axis, text):
        try:
            self._static['force'][axis] = float(text)
        except (ValueError, IndexError):
            self.app.notice.emit('力要填数字，单位 N')
        self._static.update(result=None, error='')
        self._paint()
        self.changed.emit()

    @Slot(str)
    def setQuality(self, name):
        if name in dict(QUALITIES):
            self._static.update(quality=name, result=None, error='')
            self._paint()
            self.changed.emit()

    @Slot()
    def runStatic(self):
        state = self._static
        name = self.app.session.document.props.get('material') or ''
        young, poisson, limit = materials.mechanics(name) or materials.mechanics(materials.DEFAULT_MECHANICS)
        state['material'] = name
        state.update(result=None, error='')

        def done(result, error):
            state.update(result=result, error=error)
        self._ask('static', {'fixed': list(state['fixed']), 'loaded': list(state['loaded']), 'force': list(state['force']),
                             'young': young, 'poisson': poisson, 'yield': limit, 'quality': state['quality']}, done)

    # ---- 风阻估算 ----
    @Slot(str, str)
    def setDrag(self, key, text):
        state = self._drag
        if key == 'axis':
            if text in AXES:
                state['axis'] = text
        elif key in ('speed', 'cd', 'density'):
            try:
                value = float(text)
            except ValueError:
                value = -1.0
            if value < 0:
                self.app.notice.emit('这里要填不小于 0 的数字')
            else:
                state[key] = value
        state.update(result=None, error='')
        self.changed.emit()

    @Slot()
    def runDrag(self):
        state = self._drag
        state.update(result=None, error='')

        def done(result, error):
            state.update(result=result, error=error)
        self._ask('drag', {'direction': AXES[state['axis']], 'speed': state['speed'], 'cd': state['cd'], 'density': state['density']}, done)

    # ---- 给面板的 ----
    @Property('QVariantMap', notify=changed)
    def state(self):
        tr = i18n.tr
        rows, notes, error = [], [], ''

        def add(label, value, strong=False, bad=False):
            rows.append({'label': tr(label), 'value': value, 'strong': strong, 'bad': bad})

        static, drag, assembly = self._static, self._drag, self._assembly
        info = {'mode': self._mode, 'running': bool(self._running), 'rows': rows, 'notes': notes,
                'fixed': len(static['fixed']), 'loaded': len(static['loaded']),
                'force': [number(value) for value in static['force']], 'quality': static['quality'],
                'qualities': [{'id': key, 'title': tr(title)} for key, title in QUALITIES],
                'axis': drag['axis'], 'speed': number(drag['speed']), 'cd': number(drag['cd']), 'density': number(drag['density']),
                'legend': '', 'parts': [], 'pinned': self.pinned}
        if self._mode == 'static':
            error, result = static['error'], static['result']
            name = self.app.session.document.props.get('material') or ''
            young, poisson, limit = materials.mechanics(name) or materials.mechanics(materials.DEFAULT_MECHANICS)
            add('材质', tr(name) if name else tr('未指定，按普通碳钢算'))
            add('弹性模量', number(young, 'MPa'))
            add('屈服强度', number(limit, 'MPa'))
            if result:
                add('最大应力', number(result['max_stress'], 'MPa'), strong=True)
                add('最大位移', number(result['max_displacement'], 'mm'), strong=True)
                if result.get('safety'):
                    add('安全系数', number(result['safety']), strong=True, bad=result['safety'] < 1)
                add('网格', f'{result["cells"]} × {number(result["cell_size"], "mm")}')
                info['legend'] = number(result['max_stress'], 'MPa')
                if result.get('safety') and result['safety'] < 1:
                    notes.append(tr('安全系数小于 1：按这个力会屈服'))
            notes.append(tr('这是把零件切成小方块算的估算，应力大约有 ±20% 的出入，尖角处的应力偏低；要拿它定尺寸请留足余量'))
        elif self._mode == 'drag':
            error, result = drag['error'], drag['result']
            if result:
                add('迎风面积', number(result['area'], 'mm²'))
                add('动压', number(result['pressure'], 'Pa'))
                add('阻力', number(result['force'], 'N'), strong=True)
                add('克服阻力的功率', number(result['power'], 'W'), strong=True)
            notes.append(tr('按 阻力 = ½·密度·速度²·阻力系数·迎风面积 估算；迎风面积是算出来的，阻力系数要自己填。这不是流场计算，算不出升力、压力分布和涡流'))
            notes.append(tr('阻力系数参考：方块约 1.05，圆球约 0.47，轿车约 0.3，流线体约 0.04'))
        elif self._mode == 'assembly':
            error = assembly['error']
            steps = {step['index']: step for step in assembly['steps'] or []}
            clashed = {}
            for clash in assembly['clashes'] or []:
                for own, other in ((clash['a'], clash['b']), (clash['b'], clash['a'])):
                    clashed.setdefault(own, []).append(self._parts[other]['name'] if other < len(self._parts) else '?')
            for index, part in enumerate(self._parts):
                status, state = '', ''
                step = steps.get(index)
                if step is not None:
                    if step['clash']:
                        status, state = tr('最终位置和“{}”干涉').format(tr(step['clash'])), 'bad'
                    elif step['ok']:
                        status = tr('第一个，直接放') if index == 0 else tr('能装：可以从 {} 方向装入').format(' '.join(step['directions']))
                        state = 'good'
                    else:
                        blockers = sorted(set(step['blocked'].values()))
                        status, state = tr('装不进去：六个方向都被挡住（{}）').format('、'.join(tr(name) for name in blockers)), 'bad'
                if index in clashed:
                    status = (status + '　' if status else '') + tr('和“{}”干涉').format('、'.join(tr(name) for name in clashed[index]))
                    state = 'bad'
                if index in self._red:
                    state = 'bad'
                info['parts'].append({'name': part['name'] if part['path'] else tr(part['name']), 'file': bool(part['path']),
                                      'path': part['path'], 'move': [number(value) for value in part['move']],
                                      'turn': [number(value) for value in part['turn']], 'mirror': bool(part.get('mirror')),
                                      'status': status, 'state': state, 'tint': ''})
            if assembly['clashes'] is not None:
                count = len(assembly['clashes'])
                add('干涉检查', tr('没有干涉') if not count else tr('{} 处干涉').format(count), strong=True, bad=bool(count))
                for clash in assembly['clashes']:
                    add(' ↔ '.join(tr(name) for name in clash['names']), number(clash['volume'], 'mm³'), bad=True)
            if assembly['steps'] is not None:
                fine = all(step['ok'] for step in assembly['steps'])
                add('装配顺序', tr('按这个顺序能装') if fine else tr('按这个顺序装不了'), strong=True, bad=not fine)
            notes.append(tr('列表从上到下就是装配顺序。检查的做法：每个零件沿 ±X ±Y ±Z 六个方向直线推到位，路上不撞到已经装好的零件就算能装'))
            notes.append(tr('没管的：要斜着或转着才能装进去的、工具和手伸不伸得进去、可以掰开的卡扣'))
        info['error'] = tr(error) if error else ''
        return info
