"""动作表 (快捷键和手势轮都从这里走)、快捷键设置、界面语言。"""
from __future__ import annotations

import json
import os
import sys
from PySide6.QtCore import Property, Slot

from .. import actions, i18n
from ..i18n import localized
from .common import RESERVED_KEYS
from .signals import languageChanged, settingsChanged


class ShortcutMixin:
    """动作表 (快捷键和手势轮都从这里走) (控制器的一部分)。"""

    # ---- 动作表: 快捷键和手势轮都从这里走 ----
    @Slot(str)
    def runAction(self, identifier):
        """执行动作表 (actions.py) 里的一个动作。"""
        if identifier not in actions.BY_ID:
            return
        head, _, name = identifier.partition(':')
        if self._kind != 'part':                # 装配体 / 工程图里: 建模的那些动作 (快捷键、手势轮) 都不管用
            if identifier == 'edit.delete' and self._kind == 'drawing':
                self.drawing.deleteSelected()
                return
            sketching = self._kind == 'assembly' and (head == 'tool' or identifier.startswith('sketch.')
                                                      or (self._sketch is not None and identifier.startswith('edit.')))
            if not (identifier.startswith('file.') or identifier == 'app.settings' or sketching
                    or (self._kind == 'assembly' and head in ('view', 'style') and name != 'normal')):
                return
        if head == 'cmd':
            self.startCommand(name)
        elif head == 'tool':
            self.useSketchTool(name)
        elif head == 'view':
            self.viewAction(name)
        elif head == 'style':
            self.setDisplayStyle(name)
        elif identifier == 'sketch.start':
            if self._sketch is None:            # 已经在草图里: 不做事 (免得一个字母键把草图退出去)
                self.startSketch()
        elif identifier == 'file.new':
            self.dialogRequested.emit('new')
        elif identifier == 'file.save':
            saved = {'part': self.session.document.path, 'assembly': self.sim.path, 'drawing': self.drawing.path}[self._kind]
            self.saveDocument('') if saved else self.dialogRequested.emit('save')
        elif identifier in ('file.open', 'file.export', 'app.settings'):
            self.dialogRequested.emit(identifier.partition('.')[2])
        elif identifier.startswith('sketch.') and identifier[7:] in ('pattern', 'cpattern', 'relation', 'repair', 'silhouette', 'section'):
            self.sketchPick(identifier[7:])
        else:
            {'sim.static': lambda: self.sim.open('static'), 'sim.drag': lambda: self.sim.open('drag'),
             'sim.assembly': lambda: self.sim.open('assembly'),
             'eval.measure': self.toggleMeasure, 'eval.process': self.bindProcesses, 'eval.check': self.runCheck, 'file.new': self.newDocument, 'edit.undo': self.undo, 'edit.redo': self.redo, 'edit.delete': self.deleteSelected,
             'sketch.finish': self.finishSketch, 'sketch.cancel': self.cancelSketch, 'sketch.rapid': self.toggleRapidSketch,
             'view.section': lambda: self.toggleViewSetting('section'),
             'view.perspective': lambda: self.toggleViewSetting('perspective'),
             'view.planes': lambda: self.toggleShow('main_planes')}[identifier]()

    @Property('QVariantList', notify=settingsChanged)
    def shortcuts(self):
        """现在生效的快捷键: [{'id', 'key'}...] (没有键的不在里面)。"""
        return [{'id': row['id'], 'key': self.settings.key(row['id'])} for row in actions.ACTIONS if self.settings.key(row['id'])]

    @Property('QVariantMap', notify=settingsChanged)
    def keyMap(self):
        """动作 id → 快捷键 (按钮的悬停说明里显示)。"""
        return {row['id']: self.settings.key(row['id']) for row in actions.ACTIONS}

    @Property('QVariantList', notify=settingsChanged)
    @localized
    def actionTable(self):
        """设置页里的那张表: 每个功能一行。"""
        return [dict(row, key=self.settings.key(row['id']), changed=self.settings.key(row['id']) != row['default'])
                for row in actions.ACTIONS]

    @Property('QVariantList', notify=settingsChanged)
    @localized
    def actionGroups(self):
        return list(actions.GROUPS)

    @Slot(int, int, result=str)
    def keyText(self, key, modifiers):
        """按下的键 → 快捷键的写法 ("Ctrl+Shift+Z")。只按了 Ctrl / Shift 这类修饰键时是空的。"""
        from PySide6.QtCore import QKeyCombination, Qt
        from PySide6.QtGui import QKeySequence
        if key in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_CapsLock, Qt.Key_NumLock, Qt.Key_unknown, 0):
            return ''
        try:
            held = Qt.KeyboardModifier(modifiers) & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
            return QKeySequence(QKeyCombination(held, Qt.Key(key))).toString()
        except (ValueError, TypeError):
            return ''

    @Slot(str, str)
    def setShortcut(self, identifier, key):
        """给一个功能定快捷键 (key 为空 = 不要快捷键)。这个键原来给了别的功能的, 那边自动让出来。"""
        if identifier not in actions.BY_ID:
            return
        if key.lower() in RESERVED_KEYS:
            self.notice.emit('Esc 和回车固定用来取消和确认，不能改派给别的功能')
            return
        taken = self.settings.set_key(identifier, key)
        if taken:
            names = '、'.join(f'“{actions.BY_ID[other]["title"]}”' for other in taken)
            self.notice.emit(f'{key} 原来是{names}的快捷键，现在改给“{actions.BY_ID[identifier]["title"]}”了')
        self.settingsChanged.emit()

    @Slot(str)
    def resetShortcut(self, identifier):
        if identifier in actions.BY_ID:
            self.setShortcut(identifier, actions.BY_ID[identifier]['default'])

    @Slot()
    def resetShortcuts(self):
        self.settings.reset_keys()
        self.settingsChanged.emit()

    @Property('QVariantMap', notify=settingsChanged)
    @localized
    def gestureWheels(self):
        """两套手势轮现在的 8 格: {'model': [...], 'sketch': [...]}。"""
        return {which: self._wheel_rows(which) for which in actions.GESTURES}

    @Slot(str, int, str)
    def setGesture(self, which, index, identifier):
        if which in actions.GESTURES and 0 <= index < 8 and identifier in actions.BY_ID:
            self.settings.set_wheel(which, index, identifier)
            self.settingsChanged.emit()
            self.sketchChanged.emit()

    @Slot()
    def resetGestures(self):
        self.settings.reset_wheels()
        self.settingsChanged.emit()
        self.sketchChanged.emit()

    @Property(str, constant=True)
    def settingsPath(self):
        return self.settings.file

    # ---- 界面语言 ----
    @Property(str, notify=languageChanged)
    def language(self):
        return i18n.language()

    @Property('QVariantList', constant=True)
    def languages(self):
        return [{'id': code, 'title': title} for code, title in i18n.LANGUAGES]

    @Slot(str)
    def setLanguage(self, code):
        """换界面语言 (zh / en): 立刻生效, 记进用户设置。"""
        if code == i18n.language() or code not in dict(i18n.LANGUAGES):
            return
        i18n.set_language(code)
        self.settings.set_language(code)
        self.languageChanged.emit()         # QML 里 qsTr 的文字: 启动代码接着这个信号让引擎重新翻译
        for signal in (self.changed, self.formChanged, self.sketchChanged, self.viewChanged, self.settingsChanged,
                       self.measureChanged, self.hoverTextChanged):
            signal.emit()

    @Slot(str, result=str)
    def tr(self, text):
        """一句中文 → 现在的界面语言 (提示条、视图里的文字用)。"""
        return i18n.tr(text)

    @Property('QVariantMap', constant=True)
    def aiGuide(self):
        """设置页 "AI 接口" 里给人照着抄的几段: 接 Claude Code 的命令、MCP 配置、自己写程序连的例子、说明文档在哪。"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        python = sys.executable.replace('pythonw.exe', 'python.exe')       # 桌面快捷方式用的是不带控制台的那个, MCP 要带的
        launcher = os.path.join(root, 'genform_mcp.py')
        port = self.api_port or 9631
        return {
            'port': self.api_port,
            'claude': f'claude mcp add genform -- "{python}" "{launcher}"',
            'mcp': json.dumps({'mcpServers': {'genform': {'command': python, 'args': [launcher]}}}, ensure_ascii=False, indent=2),
            'raw': 'import json, socket\n'
                   f'link = socket.create_connection(("127.0.0.1", {port}))\n'
                   'reader = link.makefile(encoding="utf-8")\n'
                   'def ask(cmd, **args):\n'
                   '    link.sendall((json.dumps({"cmd": cmd, "args": args}) + "\\n").encode("utf-8"))\n'
                   '    return json.loads(reader.readline())\n'
                   'print([tool["name"] for tool in ask("tools")["tools"]])',
            'doc': os.path.join(root, 'README.md'),
        }
