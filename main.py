# -*- coding: utf-8 -*-
"""GenForm — 给人和 AI 一起用的参数化三维建模软件。

    python main.py

本文件必须保持轻量: 内核工作进程 (multiprocessing spawn) 启动时会先导入父进程的入口模块,
这里要是直接导入界面库, 每个工作进程都白付一次界面库的启动开销。重的东西都在 __main__ 分支里才导入。
"""
import multiprocessing
import sys

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from genform.bootstrap import run
    sys.exit(run(sys.argv))
