# -*- coding: utf-8 -*-
"""命令行里跑设计检查, 和界面上点 "设计检查" 走的是同一段代码 (AppController.runCheck):

    python -m genform.check_cli 装配体.gasm      装配体: 干涉、悬空、间隙、运动干涉、紧固件、物料清单…
    python -m genform.check_cli 零件.gform       零件: 特征出错、实体、工艺…
    加 --json 输出整份结果 (默认一行一条, 报错 → 警告 → 提示)。

自己另写的检查脚本少传一个镜像、少跑一项运动干涉, 结果就和界面上看到的对不上 — 所以只留这一个入口。
退出码: 有报错 1, 没有 0, 检查本身没跑完 2。"""
from __future__ import annotations

import json
import os
import sys


def run(path, rules=None):
    """检查一个 .gasm / .gform → 和界面底部日志一样的条目 [{'level', 'code', 'title', 'detail', 'names'...}]。"""
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    from .app import AppController
    from .session import Session
    controller = AppController(Session())
    path = os.path.abspath(path)
    if path.lower().endswith('.gasm'):
        controller._set_kind('assembly')
        controller.sim.pin()
        if not controller.sim.openAssembly(path):
            raise RuntimeError(f'打不开装配体 {path}')
    else:
        replies = []
        controller.session.execute('open_document', {'path': path}, replies.append)
        if not replies or not replies[0].get('ok', True):
            raise RuntimeError((replies[0] if replies else {}).get('error') or f'打不开 {path}')
    if rules:
        controller.session.design_rules = dict(getattr(controller.session, 'design_rules', None) or {}, **rules)
    controller.runCheck()
    if controller.checkBusy:
        raise RuntimeError('检查没有同步做完')
    return controller.checkIssues


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = '--json' in argv
    files = [item for item in argv if not item.startswith('--')]
    if len(files) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        issues = run(files[0])
    except Exception as error:          # noqa: BLE001 — 命令行入口: 什么错都报出来
        print(f'检查没做完：{error}', file=sys.stderr)
        return 2
    if as_json:
        print(json.dumps(issues, ensure_ascii=False, indent=1, default=str))
    else:
        for item in issues:
            names = '、'.join(item.get('names') or [])
            print(f"{item['level'][0].upper()} {item['code']:<14} {item['title']}" + (f'  [{names}]' if names else ''))
            if item['level'] != 'info' and item.get('detail'):
                print(f"    {item['detail']}")
    return 1 if any(item['level'] == 'error' for item in issues) else 0


if __name__ == '__main__':
    sys.exit(main())
