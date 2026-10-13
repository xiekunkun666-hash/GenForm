"""退出是否干净 (手动跑): 启动 → 建一个方块 → 退出, 打印退出码; 崩溃时 app.log 里有调用栈。"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'build' / 'smoke'
PORT = 9642


def call(name, **args):
    with socket.create_connection(('127.0.0.1', PORT), timeout=10) as link:
        link.settimeout(60)
        link.sendall((json.dumps({'cmd': name, 'args': args}) + '\n').encode('utf-8'))
        return json.loads(link.makefile('rb').readline().decode('utf-8'))


OUT.mkdir(parents=True, exist_ok=True)
log = open(OUT / 'quit.log', 'w', encoding='utf-8')
process = subprocess.Popen([sys.executable, '-X', 'faulthandler', '-B', str(ROOT / 'main.py')], cwd=str(ROOT),
                           stdout=log, stderr=log, env=dict(os.environ, GENFORM_PORT=str(PORT), PYTHONIOENCODING='utf-8'))
started = time.time()
while time.time() - started < 60 and process.poll() is None:
    try:
        call('ping')
        break
    except OSError:
        time.sleep(0.3)
if 'build' in sys.argv[1:]:
    call('sketch', shapes=[{'type': 'rect', 'w': 20, 'h': 20}])
    call('extrude', distance=5)
time.sleep(1.0)
call('quit')
try:
    process.wait(20)
    print('退出码', process.returncode, hex(process.returncode & 0xFFFFFFFF))
except subprocess.TimeoutExpired:
    print('20 s 内没有退出')
os._exit(0)
