"""装配体的手动接触检查：用户请求时分段计算，模型变化只使旧结果失效。"""
from __future__ import annotations

from PySide6.QtCore import Property, QTimer, Slot

from .. import i18n, rules as design_rules
from .signals import changed

LIVE_DELAY = 350                # 毫秒: 零件变了以后等这么久再查 (连着挪几下只查最后一次)
LIVE_BUDGET = 1.5               # 秒: 一段最多算这么久


class LiveCheckMixin:
    """保留原有接口名称，检查由工具栏显式请求。"""

    def _live_init(self):
        self._live = {'on': False, 'running': False, 'done': 0, 'total': 0, 'clashes': [], 'gaps': [], 'error': '', 'result': None}
        self._live_ticket = 0
        self._live_waiters = []         # 等这一份结果的 (工具栏 "设计检查")
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(LIVE_DELAY)
        self._live_timer.timeout.connect(self._live_start)

    def _live_schedule(self):
        """零件变了使旧结果作废，不启动新的检查。"""
        self._live_ticket += 1
        self._live.update(result=None, clashes=[], gaps=[], error='', done=0, total=0)
        self._live['running'] = False
        self._live_timer.stop()
        waiters, self._live_waiters = self._live_waiters, []
        for waiter in waiters:
            waiter(None, '模型已修改，请完成建模后重新点击设计检查')
        if hasattr(self.app, '_check_model_changed'):
            self.app._check_model_changed(assembly=True)

    def _live_clear(self):
        self._live_ticket += 1
        self._live_timer.stop()
        self._live.update(running=False, result=None, clashes=[], gaps=[], error='', done=0, total=0)
        waiters, self._live_waiters = self._live_waiters, []
        for waiter in waiters:
            waiter(None, '装配体关掉了')

    def _live_start(self):
        if not self._live_waiters:
            return
        ticket = self._live_ticket
        if len(self._parts) < 1:
            self._live_done(ticket, {'pairs': [], 'floating': [], 'checked': 0}, '')
            return
        rules = design_rules.effective(getattr(self.app.session, 'design_rules', None) or {})
        data = {'parts': self._posed_parts(), 'rules': rules, 'budget': LIVE_BUDGET, 'links': self._joint_links()}
        self._live['running'] = True

        def back(result, error):
            if ticket != self._live_ticket:     # 等结果的时候零件又变了: 这份不要, 新的那一趟已经排上了
                return
            if not error and result.get('partial'):
                self._live.update(done=result['done'], total=result['total'])
                self.changed.emit()
                self.app.progressChanged.emit()
                self.app.session.query('contacts', data, back)          # 接着算: 算过的几对内核记着, 很快跳过去
                return
            self._live_done(ticket, result, error)
        self.app.session.query('contacts', data, back)
        self.changed.emit()

    def _live_done(self, ticket, result, error):
        if ticket != self._live_ticket:
            return
        pairs = (result or {}).get('pairs') or []
        self._live.update(running=False, error=error or '', result=None if error else result,
                          clashes=[pair for pair in pairs if pair['kind'] == 'clash'],
                          gaps=[pair for pair in pairs if pair['kind'] == 'gap'],
                          done=(result or {}).get('total', 0), total=(result or {}).get('total', 0))
        self._push_parts()
        self._paint()
        self.changed.emit()
        self.app.progressChanged.emit()
        waiters, self._live_waiters = self._live_waiters, []
        for waiter in waiters:
            waiter(None if error else result, error or '')

    def _live_need(self, callback):
        """显式请求检查结果；进行中的同次请求共用结果。"""
        if self._live['result'] is not None and not self._live['running']:
            callback(self._live['result'], '')
            return
        self._live_waiters.append(callback)
        if not self._live['running']:
            self._live_timer.stop()
            self._live_start()
        self.app.progressChanged.emit()

    def _live_clash_parts(self):
        found = {}
        check = getattr(self.app, '_check', {})
        if not check.get('open') or not check.get('highlight') or check.get('stale'):
            return found
        for pair in self._live['clashes']:
            found.setdefault(pair['a'], []).append(pair['b'])
            found.setdefault(pair['b'], []).append(pair['a'])
        return found

    def _live_labels(self):
        """视图里的红叉: [(文字, 重叠的地方, 'clash')...]。"""
        check = getattr(self.app, '_check', {})
        if not self.pinned or not check.get('open') or not check.get('highlight') or check.get('stale'):
            return []
        rows = []
        for pair in self._live['clashes']:
            if pair.get('point'):
                rows.append((f'{pair["names"][0]} ↔ {pair["names"][1]}  ' + i18n.tr('压进去') + f' {pair["depth"]:.2g} mm',
                             tuple(pair['point']), 'clash'))
        return rows

    @Property('QVariantMap', notify=changed)
    def live(self):
        """实时检查的样子 (视图左上角的小牌子): {'on', 'running', 'done', 'total' 对, 'clashes' 处干涉, 'gaps' 处间隙太小, 'error'}。"""
        live = self._live
        return {'on': live['on'], 'running': live['running'], 'done': live['done'], 'total': live['total'],
                'clashes': len(live['clashes']), 'gaps': len(live['gaps']), 'error': live['error']}

    @Slot()
    def toggleLive(self):
        self.app.runCheck()
