# -*- coding: utf-8 -*-
"""内核工作进程: 在独立进程里重算特征。

为什么单独一个进程: 重算可能要几秒 (界面不能卡), OpenCascade 遇到坏输入可能直接崩 (不能带走界面和
没保存的文档), 打包成机器码后在主进程里加载它也出过问题 (切片软件的教训)。

协议 (multiprocessing 管道, 一问一答):
    ('build', 序号, 特征列表, 回滚线)        → ('built', 序号, 模型数据)
    ('export', 序号, 特征列表, 回滚线, 路径) → ('exported', 序号, 错误文字或 None)
    ('outline', 序号, 特征列表, 回滚线, 哪一种, 草图坐标系) → ('outlined', 序号, 草图平面里的折线)   侧影 / 交叉曲线
    ('quit',)                                → 退出
"""


def run(connection):
    from . import build                     # 这里才加载 OpenCascade: 主进程不付这笔启动开销
    while True:
        try:
            message = connection.recv()
        except (EOFError, OSError):
            return
        kind = message[0]
        if kind == 'quit':
            return
        sequence = message[1]
        try:
            if kind == 'build':
                connection.send(('built', sequence, build.build_model(message[2], message[3])))
            elif kind == 'outline':
                connection.send(('outlined', sequence, build.outline(message[2], message[3], message[4], message[5])))
            elif kind == 'export':
                build.export(message[2], message[4], message[3])
                connection.send(('exported', sequence, None))
        except build.FeatureError as error:
            connection.send(('exported' if kind == 'export' else 'failed', sequence, str(error)))
        except Exception as error:
            connection.send(('exported' if kind == 'export' else 'failed', sequence,
                             f'内核错误 {type(error).__name__}: {error}'))
