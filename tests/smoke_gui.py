"""真窗口冒烟 (手动跑, 不在 unittest 里): 启动 GenForm → 通过 AI 接口走一遍最小闭环 → 截图 → 正常退出。

    python tests/smoke_gui.py [输出目录]

走的是内核工作进程 + 本地接口 + 渲染线程截图这条完整的路。
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build' / 'smoke'
PORT = 9641


def call(name, **args):
    with socket.create_connection(('127.0.0.1', PORT), timeout=10) as link:
        link.settimeout(120)
        link.sendall((json.dumps({'cmd': name, 'args': args}, ensure_ascii=False) + '\n').encode('utf-8'))
        data = b''
        while not data.endswith(b'\n'):
            chunk = link.recv(1 << 16)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode('utf-8'))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    log = open(OUT / 'app.log', 'w', encoding='utf-8')
    process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'main.py')], cwd=str(ROOT), stdout=log, stderr=log,
                               env=dict(os.environ, GENFORM_PORT=str(PORT), PYTHONIOENCODING='utf-8'))
    started = time.time()
    ready = False
    while time.time() - started < 60 and process.poll() is None:
        try:
            ready = call('ping').get('ok')
            break
        except OSError:
            time.sleep(0.3)
    print('就绪' if ready else '没起来', '%.1f s' % (time.time() - started), flush=True)
    failures = []
    if ready:
        def step(label, result, expect=True):
            good = bool(result.get('ok')) == expect
            print(('  通过 ' if good else '  失败 ') + label, '' if good else json.dumps(result, ensure_ascii=False)[:400], flush=True)
            if not good:
                failures.append(label)
            return result

        print('工具数', len(call('tools')['tools']), flush=True)
        step('画矩形草图', call('sketch', shapes=[{'type': 'rect', 'w': 60, 'h': 40}]))
        solid = step('拉伸 12', call('extrude', distance=12))
        step('画圆草图', call('sketch', shapes=[{'type': 'circle', 'r': 8, 'cx': 12}], offset=12))
        step('切孔', call('extrude', distance=-12, op='cut'))
        step('竖边圆角 6', call('fillet', edges='|Z', radius=6))
        step('顶面一圈倒角 1', call('chamfer', edges='>Z', distance=1))
        step('圆角过大应报错', call('fillet', edges='<Z', radius=40), expect=False)
        step('撤销', call('undo'))
        edited = step('拉伸改成 20', call('edit_feature', id=solid['id'], params={'distance': 20}))
        if edited.get('model', {}).get('body'):
            print('  实体', edited['model']['body']['size_mm'], '体积', edited['model']['body']['volume_mm3'], flush=True)
        time.sleep(0.5)
        for view in ('iso', 'top'):
            shot = step(f'截图 {view}', call('screenshot', path=str(OUT / f'view_{view}.png'), view=view))
            print('   ', shot.get('path'), flush=True)
        step('导出 STEP', call('export', path=str(OUT / 'part.step')))
        step('保存', call('save_document', path=str(OUT / 'part.gform')))
        call('quit')
    try:
        process.wait(20)
        print('退出码', process.returncode, flush=True)
    except subprocess.TimeoutExpired:
        print('20 s 内没有退出', flush=True)
        failures.append('退出')
    return 1 if failures or not ready else 0


if __name__ == '__main__':
    code = main()
    os._exit(code)
