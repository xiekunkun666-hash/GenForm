# -*- coding: utf-8 -*-
"""全局变量 (方程式): 零件里的 "变量" 特征定义名字和值 ({'values': {'D': 112, 'H': '=D/2'}}), 后面任何特征的数值参数
都可以写成 "=表达式" (比如 distance: "=H-3")。重算前先把表达式都换成数, 所以别的代码看到的都是普通数字。

装配体的全局变量 (.gasm 里的 params) 改了时, 界面把同名的值写进各个零件的变量特征 (见 sim/params.py), 零件文件自己就是最新的。
变量按出现的先后定义, 只能用前面定义过的; 写错了 → 那个特征报错 (和别的特征出错一样, 后面的不再算)。
"""
from __future__ import annotations

from ...sketchgeo.base import evaluate


def _value(text, known):
    if isinstance(text, str) and text.strip().startswith('='):
        return evaluate(text.strip()[1:], **known)
    return text


def _walk(value, known):
    if isinstance(value, dict):
        return {key: _walk(item, known) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, known) for item in value]
    return _value(value, known)


def _uses(value):
    if isinstance(value, dict):
        return any(_uses(item) for item in value.values())
    if isinstance(value, list):
        return any(_uses(item) for item in value)
    return isinstance(value, str) and value.strip().startswith('=')


def table(features, upto=None):
    """特征表里定义的变量 → {名字: 数} (到 upto 为止, 压缩了的不算)。算不出来的跳过。"""
    known = {}
    for index, feature in enumerate(features):
        if upto is not None and index >= upto:
            break
        if feature.get('type') != 'variables' or feature.get('suppressed'):
            continue
        for name, text in ((feature.get('params') or {}).get('values') or {}).items():
            try:
                known[str(name)] = float(_value(text, known))
            except (ValueError, TypeError, ZeroDivisionError):
                pass
    return known


def resolve(features):
    """→ (换好的特征表, {特征 id: 错误}). 没用变量的特征原样返回 (同一个对象), 不影响按特征表认的缓存。"""
    known, out, errors = {}, [], {}
    for feature in features:
        params = feature.get('params') or {}
        if feature.get('type') == 'variables':
            if not feature.get('suppressed'):
                for name, text in (params.get('values') or {}).items():
                    try:
                        if not str(name).isidentifier():
                            raise ValueError(f'变量名 {name!r} 不行：只能用字母、数字、下划线，不能数字开头')
                        known[str(name)] = float(_value(text, known))
                    except (ValueError, TypeError, ZeroDivisionError) as error:
                        errors[feature['id']] = f'变量 {name} 算不出来：{error}'
                        break
            out.append(feature)
            continue
        if feature.get('suppressed') or not _uses(params):
            out.append(feature)
            continue
        try:
            out.append(dict(feature, params=_walk(params, known)))
        except (ValueError, TypeError, ZeroDivisionError) as error:
            errors[feature['id']] = f'参数里的方程式算不出来：{error}'
            out.append(feature)
    return out, errors
