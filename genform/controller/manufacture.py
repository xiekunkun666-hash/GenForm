"""评估页的 绑定工艺 / 设计检查 (像 PCB 的 DRC), 和设置里的设计规则。

设计检查的结果显示在界面底部弹出来的日志窗口里 (Main.qml 的 CheckLog); 报错里提到的特征在三维视图里标红、
设计树上那一行也带红框 (_check_red), 关掉日志窗口就恢复原来的颜色。
开着的是装配体时查的是装配体 (sim.check: 零件之间的干涉、悬空, 物料清单), 条目里的 'features' 写的是 'part:序号', 标红的是零件。
"""
from __future__ import annotations

from PySide6.QtCore import Property, Signal, Slot

from .. import checks, rules as design_rules

RED = (1.0, 0.18, 0.16)


class ManufactureMixin:
    """工艺绑定和设计检查 (控制器的一部分)。"""
    checkChanged = Signal()

    def _init_manufacture(self):
        self._check = {'open': False, 'busy': False, 'issues': [], 'counts': {}, 'highlight': True, 'binding': False, 'stale': False}
        self._check_red = []
        self.session.design_rules = self.settings.rules      # 命令 (AI 接口) 和界面用同一份
        self.session.save_rules = self.settings.save

    # ---- 绑定工艺 ----
    @Property(bool, notify=checkChanged)
    def binding(self):
        return self._check['binding']

    @Slot()
    def bindProcesses(self):
        """按性价比给所有造型特征绑加工工艺 (生产数量见设计规则)。"""
        if not self.session.model.get('has_body'):
            self.notice.emit('还没有实体，没有可以绑工艺的特征')
            return
        self._check['binding'] = True
        self.checkChanged.emit()

        def done(reply):
            self._check['binding'] = False
            self.checkChanged.emit()
            if not reply.get('ok'):
                self.notice.emit(reply.get('error') or '绑定工艺失败')
                return
            counts = sorted((reply.get('processes') or {}).items(), key=lambda item: -item[1])
            text = '，'.join(f'{name} {count}' for name, count in counts[:5])
            self.notice.emit(f'按 {reply["batch"]} 件绑好了 {reply["bound"]} 个特征的工艺：{text}')
            self.changed.emit()
        self.session.execute('bind_processes', {}, done)

    # ---- 设计检查 ----
    @Property(bool, notify=checkChanged)
    def checkOpen(self):
        return self._check['open']

    @Property(bool, notify=checkChanged)
    def checkBusy(self):
        return self._check['busy']

    @Property(bool, notify=checkChanged)
    def checkStale(self):
        """检查之后模型又改过了: 日志里的结果可能不准了。"""
        return self._check['stale']

    @Property('QVariantList', notify=checkChanged)
    def checkIssues(self):
        names = {feature['id']: feature.get('name') or feature['id'] for feature in self.session.document.features}
        names.update({f'part:{index}': part['name'] for index, part in enumerate(self.sim._parts)})
        return [dict(item, names=[names.get(identifier, identifier) for identifier in item['features']])
                for item in self._check['issues']]

    @Property('QVariantMap', notify=checkChanged)
    def checkCounts(self):
        return dict(self._check['counts'])

    @Property(bool, notify=checkChanged)
    def checkHighlight(self):
        return self._check['highlight']

    @Slot()
    def runCheck(self):
        """设计检查: 全部查一遍, 结果在底部的日志窗口里, 有报错的件标红。"""
        if self._check['busy']:
            return
        self._check.update(busy=True, open=True)
        self.checkChanged.emit()

        def done(reply):
            self._check['busy'] = False
            if not reply.get('ok'):
                self._check.update(issues=[checks._issue('error', 'check_failed', '检查没做完', reply.get('error') or '')],
                                   counts={'error': 1, 'warning': 0, 'info': 0})
            else:
                self._check.update(issues=reply['issues'], counts=reply['counts'], stale=False)
            self._check_red = checks.red_features(self._check['issues']) if self._check['highlight'] else []
            self._checked_revision = self.session.document.revision
            self._mark_parts()
            self._push_appearance()
            self.checkChanged.emit()
            self.changed.emit()
        if self._kind == 'assembly':
            self.sim.check(lambda issues: done({'ok': True, 'issues': issues, 'counts': checks.summary(issues)}))
        else:
            self.session.execute('check_design', {}, done)

    @Slot()
    def closeCheck(self):
        self._check['open'] = False
        self._check_red = []
        self._mark_parts()
        self._push_appearance()
        self.checkChanged.emit()
        self.changed.emit()

    @Slot()
    def toggleCheckLog(self):
        """状态栏的日志按钮: 开着就收起; 收着时有结果就再拉出来, 还没查过就查一遍。"""
        if self._check['open']:
            self.closeCheck()
            return
        if not self._check['issues'] and not self._check['busy']:
            self.runCheck()
            return
        self._check['open'] = True
        self._check_red = checks.red_features(self._check['issues']) if self._check['highlight'] else []
        self._mark_parts()
        self._push_appearance()
        self.checkChanged.emit()
        self.changed.emit()

    @Slot()
    def toggleCheckHighlight(self):
        self._check['highlight'] = not self._check['highlight']
        self._check_red = checks.red_features(self._check['issues']) if self._check['highlight'] and self._check['open'] else []
        self._mark_parts()
        self._push_appearance()
        self.checkChanged.emit()
        self.changed.emit()

    @Slot(int)
    def focusIssue(self, index):
        """日志里点了一条: 选中它提到的第一个特征 (设计树滚到那一行, 视图里高亮)。"""
        issues = self._check['issues']
        if 0 <= index < len(issues) and issues[index]['features']:
            first = issues[index]['features'][0]
            if str(first).startswith('part:'):          # 装配体: 只把这一条说的零件标红
                self.sim.mark([int(identifier[5:]) for identifier in issues[index]['features'] if str(identifier).startswith('part:')])
            else:
                self.selectFeature(first)

    def _check_colors(self):
        """视图里要标红的特征 → 颜色 (盖在用户自己上的颜色上面)。装配体的零件 ('part:序号') 由 _mark_parts 标。"""
        return {identifier: RED for identifier in self._check_red if not str(identifier).startswith('part:')}

    def _mark_parts(self):
        """装配体: 检查报错的零件在视图里整个标红 (sim.mark); 关掉日志 / 不标红时恢复。"""
        if self._kind == 'assembly':
            self.sim.mark([int(identifier[5:]) for identifier in self._check_red if str(identifier).startswith('part:')])

    def _check_model_changed(self):
        if self._check['open'] and getattr(self, '_checked_revision', None) != self.session.document.revision and not self._check['stale']:
            self._check['stale'] = True
            self.checkChanged.emit()

    # ---- 设计规则 (设置 → 设计规则) ----
    @Property('QVariantList', notify=checkChanged)
    def designRules(self):
        values = design_rules.effective(self.settings.rules)
        return [dict(row, value=values[row['key']], changed=row['key'] in self.settings.rules) for row in design_rules.table()]

    @Slot(str, str)
    def setRule(self, key, text):
        cleaned = design_rules.clean({key: text})
        if key not in cleaned:
            self.notice.emit('这里要填数字')
            self.checkChanged.emit()
            return
        if cleaned[key] == design_rules.DEFAULTS[key]:
            self.settings.rules.pop(key, None)
        else:
            self.settings.rules[key] = cleaned[key]
        self.settings.save()
        self.checkChanged.emit()

    @Slot()
    def resetRules(self):
        self.settings.rules.clear()
        self.settings.save()
        self.checkChanged.emit()
