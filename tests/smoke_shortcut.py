"""按桌面快捷方式的方式 (pythonw, 没有控制台) 启动, 建一个方块, 正常退出 — 手动跑。"""
import json
import os
import socket
import subprocess
import time

PORT = 9644


def call(name, **args):
    with socket.create_connection(('127.0.0.1', PORT), timeout=10) as link:
        link.settimeout(60)
        link.sendall((json.dumps({'cmd': name, 'args': args}) + '\n').encode('utf-8'))
        return json.loads(link.makefile('rb').readline().decode('utf-8'))


process = subprocess.Popen([r'C:\qt_project\venv313\Scripts\pythonw.exe', '-B', r'C:\qt_project\GenForm\main.py'],
                           cwd=r'C:\qt_project\GenForm', env=dict(os.environ, GENFORM_PORT=str(PORT)))
started = time.time()
ready = False
while time.time() - started < 60 and process.poll() is None:
    try:
        ready = call('ping')['ok']
        break
    except OSError:
        time.sleep(0.3)
print('就绪' if ready else '没起来', '%.1f s' % (time.time() - started))
if ready:
    call('sketch', shapes=[{'type': 'rect', 'w': 20, 'h': 20}])
    print('拉伸', call('extrude', distance=5)['ok'])
    call('quit')
try:
    process.wait(20)
    print('退出码', process.returncode)
except subprocess.TimeoutExpired:
    print('没有退出')
print(end='', flush=True)       # os._exit 不冲缓冲: 输出接到管道时不先冲一下就全丢了
os._exit(0)
