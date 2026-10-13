"""草图页第二批工具的界面检查 (手动跑): 中心线、各种矩形 / 槽口、周边圆、样式样条、方程式曲线 → 智能尺寸、
几何关系、圆周阵列、延伸 → 拉一个圆柱 → 侧影实体、交叉曲线 → 3D 草图。每一步抓一张窗口画面到 build/smoke/s2_*.png。

    python tests/smoke_sketch2.py

鼠标位置按草图里的毫米写 (刚进草图时视图中心是原点, 横向一整屏约 375 mm、纵向约 238 mm)。
"""
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

_helpers = (Path(__file__).resolve().parent / 'smoke_ui.py').read_text(encoding='utf-8').split('OUT.mkdir')[0]
exec(_helpers.replace('PORT = 9643', 'PORT = 9642'))

OUT.mkdir(parents=True, exist_ok=True)
log = open(OUT / 'sketch2.log', 'w', encoding='utf-8')
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
        ui('_debug_mouse', kind, 0.5 + x / 375.0, 0.5 - y / 238.0)

    def click(x, y):
        mouse('move', x, y); mouse('press', x, y); mouse('release', x, y)

    def clicks(tool, *spots):
        ui('sketchPick', tool)
        for x, y in spots:
            click(x, y)

    def drag(x0, y0, x1, y1):
        mouse('press', x0, y0)
        for step in range(1, 6):
            mouse('move', x0 + (x1 - x0) * step / 5, y0 + (y1 - y0) * step / 5)
        mouse('release', x1, y1)

    def sketch_shapes(index):
        return call('get_model')['features'][index]['params']['shapes']

    time.sleep(1.0)
    PID = call('ping')['pid']
    ui('setTab', 'sketch')
    time.sleep(0.3)
    grab(PID, 's2_0_ribbon.png')
    ui('useSketchTool', 'centerline')
    ui('selectPlane', 'XY')
    time.sleep(0.8)
    click(-160, -90); click(-160, 90)
    ui('enterKey')
    clicks('midline', (-130, 80), (-110, 80))
    clicks('crect', (-70, 75), (-50, 90))
    clicks('rect3', (-30, 65), (10, 65), (10, 90))
    clicks('crect3', (50, 78), (70, 78), (70, 90))
    clicks('pgram', (95, 65), (135, 65), (150, 90))
    clicks('circle3', (-130, 40), (-120, 50), (-110, 40))
    clicks('cslot', (-70, 40), (-50, 40), (-50, 47))
    clicks('aslot3', (10, 30), (-30, 30), (-10, 50))
    mouse('move', -10, 56)
    time.sleep(0.3)
    grab(PID, 's2_1_arcslot_drawing.png')
    click(-10, 56)
    clicks('caslot', (60, 25), (85, 25))
    for degrees in range(10, 91, 10):
        mouse('move', 60 + 25 * math.cos(math.radians(degrees)), 25 + 25 * math.sin(math.radians(degrees)))
    click(60, 50); click(60, 56)
    clicks('sspline', (100, 25), (115, 50), (135, 50), (150, 25))
    ui('enterKey')
    clicks('equation', (-150, -20))
    time.sleep(0.3)
    grab(PID, 's2_2_drawn.png')

    clicks('circle', (-40, -20), (-32, -20))
    clicks('circle', (0, -20), (8, -20))
    clicks('dimension', (-32, -20))
    time.sleep(0.3)
    grab(PID, 's2_3_dimension_single.png')
    ui('setField', 'd', 24)
    click(8, -20)
    ui('setField', 'distance', 60)
    time.sleep(0.3)
    grab(PID, 's2_4_dimension_distance.png')
    ui('acceptForm')

    clicks('line', (60, -10), (110, -10))
    ui('enterKey')
    clicks('line', (60, -30), (105, -22))
    ui('enterKey')
    ui('sketchPick', 'select')
    drag(55, -36, 116, -4)
    ui('sketchRelation')
    ui('setField', 'choice', 'parallel')
    time.sleep(0.3)
    grab(PID, 's2_5_relation.png')
    ui('acceptForm')

    clicks('circle', (-100, -70), (-96, -70))
    time.sleep(0.3)
    grab(PID, 's2_5b_small_circle.png')
    clicks('select', (-96, -70))
    time.sleep(0.3)
    grab(PID, 's2_5c_small_circle_selected.png')
    ui('sketchPick', 'cpattern')
    ui('setField', 'cx', -120)
    ui('setField', 'cy', -70)
    ui('setField', 'count', 6)
    time.sleep(0.3)
    grab(PID, 's2_6_circular_pattern.png')
    ui('acceptForm')

    clicks('line', (0, -60), (30, -60))
    ui('enterKey')
    clicks('line', (60, -80), (60, -40))
    ui('enterKey')
    clicks('extend', (28, -60))
    ui('toggleSnap', 'grid')
    clicks('point', (33.37, -91.23))                    # 网格捕捉关着: 点留在点下去的地方
    ui('toggleSnap', 'grid')
    ui('sketchPick', 'select')
    time.sleep(0.3)
    grab(PID, 's2_7_all.png')
    ui('finishSketch')
    time.sleep(1.5)
    made = sketch_shapes(0)
    kinds = [shape['type'] + ('*' if shape.get('construction') else '') for shape in made]
    print('图形', len(made), kinds, flush=True)
    by = {}
    for shape in made:
        by.setdefault(shape['type'], []).append(shape)
    circles = sorted((round(s['cx'], 2), round(s['cy'], 2), round(s['r'], 2)) for s in by['circle'])
    print('圆', circles, flush=True)
    print('直线', [(round(s['x1'], 2), round(s['y1'], 2), round(s['x2'], 2), round(s['y2'], 2)) for s in by['line']], flush=True)
    print('圆弧槽口', [(round(s['r'], 2), round(s['w'], 2), round(s['a0'], 1), round(s['a1'], 1)) for s in by.get('arcslot', [])], flush=True)
    print('点', [(s['x'], s['y']) for s in by.get('point', [])], flush=True)
    print('草图状态', call('get_model')['features'][0].get('status'), flush=True)

    ui('useSketchTool', 'circle')                       # 一个圆柱: 侧着看它
    ui('selectPlane', 'XY')
    time.sleep(0.8)
    click(0, 0); click(30, 0)
    ui('startCommand', 'extrude')
    time.sleep(1.2)
    ui('setField', 'distance', 40)
    ui('acceptForm')
    time.sleep(1.5)
    ui('setTab', 'sketch')
    ui('useSketchTool', 'point')
    ui('selectPlane', 'XZ')
    time.sleep(0.9)
    ui('sketchPick', 'silhouette')
    time.sleep(1.5)
    mouse('move', -30, 20)
    time.sleep(0.3)
    grab(PID, 's2_8_silhouette.png')
    click(-30, 20)                                      # 圆柱转过去的那条侧边
    ui('sketchPick', 'section')
    time.sleep(1.5)
    mouse('move', 0, 40)
    time.sleep(0.3)
    grab(PID, 's2_9_section.png')
    click(0, 40)                                        # 交线的上边
    ui('finishSketch')
    time.sleep(1.5)
    model = call('get_model')
    print('转换进来的', [(s['type'], round(s.get('x1', 0), 2), round(s.get('y1', 0), 2), round(s.get('x2', 0), 2), round(s.get('y2', 0), 2))
                    for s in model['features'][-1]['params']['shapes']], flush=True)

    ui('startCommand', 'sketch3d')
    time.sleep(0.6)
    grab(PID, 's2_10_sketch3d_form.png')
    ui('acceptForm')
    time.sleep(1.5)
    ui('setView', 'iso')
    time.sleep(1.0)
    grab(PID, 's2_11_sketch3d.png')
    print('特征', [(feature['name'], feature['type'], feature.get('status')) for feature in call('get_model')['features']], flush=True)
finally:
    ask({'cmd': 'quit'})
    try:
        process.wait(20)
        print('退出码', process.returncode, flush=True)
    except subprocess.TimeoutExpired:
        print('没有退出', flush=True)
print(end='', flush=True)
os._exit(0)
