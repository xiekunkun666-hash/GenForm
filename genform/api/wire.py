# -*- coding: utf-8 -*-
"""接口两端 (窗口里的服务、MCP 适配) 共用的小东西; 不依赖界面库。"""
import json

DEFAULT_PORT = 9631


def encode(value):
    """结果里可能混着 numpy 数和元组: 统一成 JSON 能写的类型。"""
    def plain(item):
        if isinstance(item, dict):
            return {str(key): plain(entry) for key, entry in item.items()}
        if isinstance(item, (list, tuple)):
            return [plain(entry) for entry in item]
        if hasattr(item, 'tolist'):
            return item.tolist()
        return item
    return json.dumps(plain(value), ensure_ascii=False)
