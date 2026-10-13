# -*- coding: utf-8 -*-
"""用户的设置 (快捷键、右键手势轮): 存在用户目录下的一个 JSON 文件里, 和零件文档无关。

位置: %APPDATA%\\GenForm\\settings.json; 环境变量 GENFORM_SETTINGS 可以换一个文件 (自动化测试用, 免得动到用户自己的设置)。
文件坏了或读不了就当没有: 设置丢了只是回到默认, 不能因为它打不开软件。
"""
from __future__ import annotations

import json
import os

from . import actions


def path():
    custom = os.environ.get('GENFORM_SETTINGS')
    if custom:
        return custom
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'GenForm', 'settings.json')


class Settings:
    def __init__(self, file=None):
        self.file = file or path()
        self.keys = {}          # 动作 id → 快捷键 (只存和默认不一样的; '' = 用户把它清掉了)
        self.gestures = {}      # 'model' / 'sketch' → 8 个动作 id (只存改过的那一套)
        self.load()

    def load(self):
        try:
            with open(self.file, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        keys = data.get('shortcuts')
        if isinstance(keys, dict):
            self.keys = {str(name): str(key) for name, key in keys.items() if name in actions.BY_ID}
        wheels = data.get('gestures')
        if isinstance(wheels, dict):
            for which, rows in wheels.items():
                if which in actions.GESTURES and isinstance(rows, list) and len(rows) == 8 \
                        and all(row in actions.BY_ID for row in rows):
                    self.gestures[which] = [str(row) for row in rows]

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.file), exist_ok=True)
            with open(self.file, 'w', encoding='utf-8') as handle:
                json.dump({'shortcuts': self.keys, 'gestures': self.gestures}, handle, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # ---- 快捷键 ----
    def key(self, identifier):
        return self.keys.get(identifier, actions.BY_ID[identifier]['default'])

    def set_key(self, identifier, key):
        """给一个动作定快捷键 (key='' = 不要快捷键)。同一个键原来给了别的动作的, 那个动作的清掉。→ 被清掉的动作 id 列表。"""
        taken = [other for other in actions.BY_ID if other != identifier and key and self.key(other).lower() == key.lower()]
        for other in taken:
            self.keys[other] = ''
        if key == actions.BY_ID[identifier]['default']:
            self.keys.pop(identifier, None)
        else:
            self.keys[identifier] = key
        self.save()
        return taken

    def reset_keys(self):
        self.keys = {}
        self.save()

    # ---- 手势轮 ----
    def wheel(self, which):
        return list(self.gestures.get(which, actions.GESTURES[which]))

    def set_wheel(self, which, index, identifier):
        rows = self.wheel(which)
        rows[index] = identifier
        if rows == actions.GESTURES[which]:
            self.gestures.pop(which, None)
        else:
            self.gestures[which] = rows
        self.save()

    def reset_wheels(self):
        self.gestures = {}
        self.save()
