"""草图工具的界面检查 (手动跑): 启动 → 进草图 → 每个画图工具画一个 → 圆角、剪裁、等距、镜向、阵列、修复 →
完成并拉伸 → 转换实体引用 → 快速草图。每一步抓一张窗口画面到 build/smoke/sk_*.png。

    python tests/smoke_sketch.py

鼠标位置写的是三维视图宽高的比例。刚进草图 (上视) 时视图中心是原点, 横向一整屏约 375 mm、纵向约 238 mm。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# 开窗口、发命令、抓图的那几个函数和 smoke_ui.py 是同一套: 直接拿它的前半段 (到启动程序之前) 来用
_helpers = (Path(__file__).resolve().parent / 'smoke_ui.py').read_text(encoding='utf-8').split('OUT.mkdir')[0]
exec(_helpers.replace('PORT = 9643', 'PORT = 9645'))

OUT.mkdir(parents=True, exist_ok=True)
log = open(OUT / 'sketch.log', 'w', encoding='utf-8')
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

    def clicks(tool, *spots):
        ui('setSketchTool', tool)
        for x, y in spots:
            click(x, y)

    def drag(x0, y0, x1, y1):
        mouse('press', x0, y0)
        for step in range(1, 6):
            mouse('move', x0 + (x1 - x0) * step / 5, y0 + (y1 - y0) * step / 5)
        mouse('release', x1, y1)

    def shapes():
        return [shape['type'] for shape in call('get_model')['features'][0]['params']['shapes']]

    time.sleep(1.0)
    PID = call('ping')['pid']
    ui('setTab', 'sketch')
    grab(PID, 'sk_0_ribbon.png')
    ui('useSketchTool', 'rect')
    ui('selectPlane', 'XY')
    time.sleep(0.8)
    drag(0.30, 0.30, 0.45, 0.45)
    clicks('circle', (0.55, 0.38), (0.59, 0.38))
    ui('setSketchTool', 'arc')
    click(0.70, 0.38); click(0.76, 0.38)
    mouse('move', 0.74, 0.32); mouse('move', 0.70, 0.30)
    click(0.64, 0.38)
    clicks('slot', (0.30, 0.62), (0.42, 0.62), (0.42, 0.66))
    clicks('ngon', (0.52, 0.62), (0.56, 0.62))
    clicks('ellipse', (0.68, 0.62), (0.76, 0.62), (0.70, 0.67))
    clicks('spline', (0.30, 0.82), (0.36, 0.76), (0.42, 0.84), (0.48, 0.77))
    mouse('move', 0.50, 0.80)
    time.sleep(0.3)
    grab(PID, 'sk_1_spline_drawing.png')
    ui('enterKey')
    clicks('point', (0.55, 0.82))
    clicks('text', (0.62, 0.84))
    ui('setField', 'text', 'GenForm 草图')
    time.sleep(0.3)
    grab(PID, 'sk_2_all_shapes.png')

    clicks('fillet', (0.45, 0.30))                      # 矩形右上角
    clicks('line', (0.50, 0.38), (0.61, 0.38))          # 横穿圆的一条线
    ui('enterKey')
    clicks('trim', (0.55, 0.317))                       # 剪掉圆的上半边
    clicks('offset', (0.755, 0.62), (0.79, 0.62))       # 椭圆往外等距
    clicks('select', (0.56, 0.62))                      # 选中多边形
    clicks('mirror', (0.40, 0.70), (0.60, 0.70))        # 关于一条水平线镜向到下面
    time.sleep(0.3)
    grab(PID, 'sk_3_modified.png')
    clicks('select', (0.55, 0.82))                      # 选中那个点
    ui('sketchPattern')
    ui('setField', 'nx', 4)
    ui('setField', 'dx', 6)
    time.sleep(0.3)
    grab(PID, 'sk_4_pattern.png')
    ui('acceptForm')
    ui('sketchRepair')
    time.sleep(0.3)
    grab(PID, 'sk_5_repair.png')
    ui('cancelForm')
    ui('setQuickSnap', 'center')
    ui('setSketchTool', 'line')
    mouse('move', 0.57, 0.40)                           # 圆心附近 (平时吸不到这么远)
    time.sleep(0.3)
    grab(PID, 'sk_6_quick_snap.png')
    ui('escape')
    ui('startCommand', 'extrude')                       # 存草图, 接着拉伸
    time.sleep(1.2)
    print('图形', shapes(), flush=True)
    ui('setField', 'distance', 6)
    ui('acceptForm')
    time.sleep(1.5)
    model = call('get_model')
    print('拉伸', model['features'][1].get('status'), model.get('body', {}).get('size_mm'), flush=True)
    grab(PID, 'sk_7_solid.png')

    ui('editFeature', 'f1')                             # 回到草图: 看转换实体引用
    time.sleep(0.9)
    ui('setSketchTool', 'convert')
    mouse('move', 0.5, 0.5)
    time.sleep(0.3)
    grab(PID, 'sk_8_convert.png')
    ui('cancelSketch')
    time.sleep(0.6)

    ui('toggleRapidSketch')                             # 快速草图: 不转视角, 画完接着选面
    ui('setTab', 'sketch')
    ui('useSketchTool', 'circle')
    ui('selectPlane', 'XZ')
    time.sleep(0.5)
    drag(0.40, 0.25, 0.46, 0.25)
    time.sleep(0.3)
    grab(PID, 'sk_9_rapid_drawing.png')
    ui('finishSketch')
    time.sleep(1.0)
    grab(PID, 'sk_10_rapid_next_plane.png')
    ui('escape')
    print('特征', [(feature['name'], feature.get('status')) for feature in call('get_model')['features']], flush=True)
finally:
    ask({'cmd': 'quit'})
    try:
        process.wait(20)
        print('退出码', process.returncode, flush=True)
    except subprocess.TimeoutExpired:
        print('没有退出', flush=True)
print(end='', flush=True)
os._exit(0)
