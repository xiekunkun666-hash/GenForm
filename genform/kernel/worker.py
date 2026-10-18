# -*- coding: utf-8 -*-
"""内核工作进程: 在独立进程里重算特征。

为什么单独一个进程: 重算可能要几秒 (界面不能卡), OpenCascade 遇到坏输入可能直接崩 (不能带走界面和
没保存的文档), 打包成机器码后在主进程里加载它也出过问题 (切片软件的教训)。

协议 (multiprocessing 管道, 一问一答):
    ('build', 序号, 特征列表, 回滚线)        → ('built', 序号, 模型数据); 算的过程中另外发若干条
                                               ('progress', 序号, (做到第几个特征, 一共几个, 特征名))
                                               (查询自己报的进度多一项, 如装配体加载: (第几个零件, 一共几个, 名字, 'parts'))
    ('export', 序号, 特征列表, 回滚线, 路径) → ('exported', 序号, 错误文字或 None)
    ('outline', 序号, 特征列表, 回滚线, 哪一种, 草图坐标系) → ('outlined', 序号, 草图平面里的折线)   侧影 / 交叉曲线
    ('quit',)                                → 退出
"""


import time


def run(connection):
    from . import build                     # 这里才加载 OpenCascade: 主进程不付这笔启动开销
    from .model import rebuild as steps     # 重算的进度回调设在它上面 (build 只是转名字的门面)
    sent = None                             # 上一次送过去的那份实体显示数据 (build._SHOWN 里的那个字典)
    while True:
        try:
            message = connection.recv()
        except (EOFError, OSError):
            return
        kind = message[0]
        if kind == 'quit':
            return
        sequence = message[1]
        last = [0.0]

        def report(index, total, name, *more, sequence=sequence):
            # 一秒最多一百条: 特征算得快时不刷屏; 但也不能省太多 — 界面的看门狗靠它知道正在算哪个特征 (卡住了报得出名字)
            if time.perf_counter() - last[0] >= 0.01:
                last[0] = time.perf_counter()
                connection.send(('progress', sequence, (index, total, name, *more)))
        steps.on_step = report              # 导出、试算也要重算: 一样报, 看门狗才不会把算得久的大零件当成卡死
        try:
            if kind == 'build':
                model = build.build_model(message[2], message[3])
                shown = build._SHOWN[1] if build._SHOWN and model.get('has_body') else None
                if shown is not None and shown is sent:
                    # 实体和上一次送过去的是同一个: 只送变了的 (状态、草图线), 那边接着用它手里的网格
                    model = {key: value for key, value in model.items() if key not in shown}
                    model['same_body'] = True
                sent = shown
                connection.send(('built', sequence, model))
            elif kind == 'outline':
                connection.send(('outlined', sequence, build.outline(message[2], message[3], message[4], message[5])))
            elif kind == 'keep':            # 文档刚保存: 把现在算好的样子也存到磁盘缓存里 (不回话)
                build.rebuild(message[2], message[3])
                build.keep()
                connection.send(('kept', sequence, None))
            elif kind == 'export':
                build.export(message[2], message[4], message[3])
                connection.send(('exported', sequence, None))
        except build.FeatureError as error:
            connection.send(('exported' if kind == 'export' else 'failed', sequence, str(error)))
        except Exception as error:
            connection.send(('exported' if kind == 'export' else 'failed', sequence,
                             f'内核错误 {type(error).__name__}: {error}'))
        finally:
            steps.on_step = None
