# -*- coding: utf-8 -*-
"""界面语言: 中文 (源码里写的就是中文) 和英文 (对照表在 assets/lang_en.json: 中文句子 → 英文)。

源码里的中文句子就是翻译的 "键": QML 里用 qsTr("中文"), Python 里给界面的数据在出口处过一遍 localize。
对照表里有整句的用整句; 没有的 (带数字、名字拼出来的句子) 把里面认识的词和短语换掉, 剩下的保持原样 —
所以漏翻的地方会露出中文, 不会出错。
"""
from __future__ import annotations

import json
import os
import re

LANGUAGES = [('zh', '中文'), ('en', 'English')]
_CJK = re.compile(r'[一-鿿]')
_state = {'lang': 'zh', 'table': {}, 'pattern': None, 'cache': {}}
_SKIP = ('id', 'icon', 'key', 'default', 'kind', 'type', 'mark', 'tint', 'state', 'accept_key')


def language():
    return _state['lang']


def set_language(code):
    if code not in dict(LANGUAGES):
        code = 'zh'
    _state.update(lang=code, cache={})
    if code == 'en' and not _state['table']:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'lang_en.json'), encoding='utf-8') as source:
            EN = json.load(source)
        _state['table'] = EN
        # 拼出来的句子: 把认识的短语换掉, 长的先换 (免得 "圆柱面" 被 "圆" 抢先)
        parts = sorted((key for key in EN if len(key) >= 2 and _CJK.search(key)), key=len, reverse=True)
        _state['pattern'] = re.compile('|'.join(re.escape(part) for part in parts)) if parts else None


def tr(text):
    """一句中文 → 现在的界面语言。"""
    if _state['lang'] == 'zh' or not isinstance(text, str) or not _CJK.search(text):
        return text
    cache = _state['cache']
    found = cache.get(text)
    if found is None:
        table = _state['table']
        found = table.get(text)
        if found is None:
            pattern = _state['pattern']
            found = pattern.sub(lambda match: table[match.group(0)], text) if pattern else text
            if len(_CJK.findall(found)) * 3 > len(_CJK.findall(text)):      # 大半没认出来: 半中半英更难看, 整句留着中文
                found = text
            found = found.replace('（', ' (').replace('）', ') ').replace('：', ': ').replace('，', ', ').replace('。', '. ') \
                         .replace('；', '; ').replace('、', ', ').replace('“', '"').replace('”', '"').replace('　', '  ').strip()
        if len(cache) < 20000:
            cache[text] = found
    return found


def localize(value):
    """给界面的数据 (字符串 / 列表 / 字典套着) 里的中文都换成现在的语言。id、图标名这些不动; 用户自己填的值也不动。"""
    if _state['lang'] == 'zh':
        return value
    if isinstance(value, str):
        return tr(value)
    if isinstance(value, (list, tuple)):
        return [localize(item) for item in value]
    if isinstance(value, dict):
        field = 'key' in value and value.get('type') != 'info'       # 参数面板上的一项: 它的值是用户填的
        return {key: item if key in _SKIP or (field and key == 'value') else localize(item) for key, item in value.items()}
    return value


def localized(function):
    """装饰器: 这个取数的方法给出去之前过一遍 localize。"""
    def wrapper(*args, **kwargs):
        return localize(function(*args, **kwargs))
    wrapper.__name__ = function.__name__
    wrapper.__doc__ = function.__doc__
    return wrapper
