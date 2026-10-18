# -*- coding: utf-8 -*-
"""给 AI 工具用的启动器: 把 GenForm 接成一个 MCP 服务。

    python genform_mcp.py              连到正在运行的 GenForm 窗口 (AI 画的时候人看得见)
    python genform_mcp.py --headless   不开窗口, 自己带一份文档 (截图、视角这类要窗口的工具不可用)

和 python -m genform.api.mcp_server 是一回事; 单独放一个文件是为了在 AI 工具的配置里只写一个绝对路径就行,
不用管工作目录和 PYTHONPATH。端口不是默认的 9631 时, 设环境变量 GENFORM_PORT。详见 README.md。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    from genform.api.mcp_server import main
    main()
