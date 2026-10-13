"""特征页的界面检查 (手动跑): 启动 → 用面板做抽壳 (在视图里点面)、在新建的基准面上画草图并拉伸、线性阵列 →
再用接口加上孔、螺旋线扫描、参考几何体 → 每一步抓一张窗口画面到 build/smoke/ft_*.png。

    python tests/smoke_features.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# 开窗口、发命令、抓图的那几个函数和 smoke_ui.py 是同一套: 直接拿它的前半段 (到启动程序之前) 来用
_helpers = (Path(__file__).resolve().parent / 'smoke_ui.py').read_text(encoding='utf-8').split('OUT.mkdir')[0]
exec(_helpers.replace('PORT = 9643', 'PORT = 9646'))

OUT.mkdir(parents=True, exist_ok=True)
log = open(OUT / 'features.log', 'w', encoding='utf-8')
process = subprocess.Popen([sys.executable, '-B', str(ROOT / 'main.py')], cwd=str(ROOT), stdout=log, stderr=log,
                           env=dict(os.environ, GENFORM_PORT=str(PORT), PYTHONIOENCODING='utf-8'))
started = time.time()
while time.time() - started < 60 and process.poll() is None:
    try:
        call('ping')
        break
    except OSError:
        time.sleep(0.3)
try:
    def mouse(kind, x, y):
        ui('_debug_mouse', kind, x, y)

    def click(x, y):
        mouse('move', x, y); mouse('press', x, y); mouse('release', x, y)

    def drag(x0, y0, x1, y1):
        mouse('press', x0, y0)
        for step in range(1, 6):
            mouse('move', x0 + (x1 - x0) * step / 5, y0 + (y1 - y0) * step / 5)
        mouse('release', x1, y1)

    def do(command, **args):
        reply = call(command, **args)
        print(('  成功 ' if reply.get('ok') else '  失败 ') + command, reply.get('id', ''), reply.get('error', ''), flush=True)
        return reply.get('id')

    def body():
        return call('get_model').get('body', {})

    time.sleep(1.0)
    PID = call('ping')['pid']
    do('extrude', sketch=do('sketch', shapes=[{'type': 'rect', 'cx': 0, 'cy': 0, 'w': 80, 'h': 60}]), distance=30)
    time.sleep(0.5)
    grab(PID, 'ft_0_ribbon.png')

    ui('startCommand', 'shell')                         # 抽壳: 面板开着, 在视图里点顶面
    time.sleep(0.3)
    click(0.5, 0.42)
    time.sleep(0.3)
    grab(PID, 'ft_1_shell_form.png')
    ui('acceptForm')
    time.sleep(1.0)
    print('抽壳后体积', body().get('volume_mm3'), '应为', 80 * 60 * 30 - 76 * 56 * 28, flush=True)

    plane = do('plane', base='XZ', offset=30, angle=0)  # 前面板上的基准面
    ui('selectFeature', plane)
    ui('setTab', 'sketch')
    ui('useSketchTool', 'circle')                       # 选着基准面特征点 "圆": 直接在它上面画
    time.sleep(0.9)
    click(0.5, 0.45)
    mouse('move', 0.54, 0.45)
    time.sleep(0.3)
    grab(PID, 'ft_2_sketch_on_plane.png')
    click(0.54, 0.45)
    ui('startCommand', 'extrude')                       # 存草图, 接着拉伸
    time.sleep(1.0)
    ui('setField', 'distance', 12)
    ui('acceptForm')
    time.sleep(1.0)
    boss = call('get_model')['features'][-1]
    print('基准面上的凸台', boss['name'], boss['status'], body().get('size_mm'), flush=True)

    ui('selectFeature', boss['id'])
    ui('startCommand', 'pattern_linear')                # 选着凸台点线性阵列: 对象已经填好
    ui('setField', 'axis1', 'X')
    ui('setField', 'count1', 2)
    ui('setField', 'spacing1', 25)
    time.sleep(0.3)
    grab(PID, 'ft_3_pattern_form.png')
    ui('acceptForm')
    time.sleep(1.0)

    spots = do('sketch', shapes=[{'type': 'point', 'x': -25, 'y': 15}, {'type': 'point', 'x': 25, 'y': 15}], offset=0)
    do('hole', sketch=spots, kind='counterbore', size='M5', flip=True)
    helix = do('curve_helix', sketch=do('sketch', shapes=[{'type': 'circle', 'cx': 0, 'cy': 0, 'r': 12}], offset=30), pitch=6, turns=4)
    do('sweep', sketch=do('sketch', shapes=[{'type': 'circle', 'cx': 12, 'cy': 30, 'r': 1.5}], plane='XZ'), path=helix)
    do('axis', origin=[[0, 0, 0]], direction=[[0, 0, 1]])
    do('csys', origin=[[-40, -30, 0]])
    ui('startCommand', 'bbox')                          # 没有参数的: 点了直接加
    ui('startCommand', 'com')
    time.sleep(1.5)
    grab(PID, 'ft_4_part.png')
    ui('startCommand', 'pattern_fill')
    time.sleep(0.3)
    grab(PID, 'ft_5_fill_form.png')
    ui('cancelForm')
    ui('startCommand', 'revolve_cut')
    time.sleep(0.3)
    grab(PID, 'ft_6_revolve_cut_form.png')
    ui('cancelForm')
    print('特征', [(feature['name'], feature['status'][:20]) for feature in call('get_model')['features']], flush=True)
finally:
    ask({'cmd': 'quit'})
    try:
        process.wait(20)
        print('退出码', process.returncode, flush=True)
    except subprocess.TimeoutExpired:
        print('没有退出', flush=True)
print(end='', flush=True)
os._exit(0)
