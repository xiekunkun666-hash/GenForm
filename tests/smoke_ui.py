"""界面外观检查 (手动跑): 启动 → 建一个零件 → 模拟用户打开圆角面板并选边 → 抓整个窗口的屏幕画面。

    python tests/smoke_ui.py

抓的是屏幕上窗口所在的那一块, 所以运行时别让其他窗口盖住它。
"""
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'build' / 'smoke'
PORT = 9643


def ask(request):
    with socket.create_connection(('127.0.0.1', PORT), timeout=10) as link:
        link.settimeout(60)
        link.sendall((json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8'))
        return json.loads(link.makefile('rb').readline().decode('utf-8'))


def call(name, **args):
    return ask({'cmd': name, 'args': args})


def ui(slot, *args):
    return ask({'cmd': 'ui', 'slot': slot, 'args': list(args)})


def window_rect(pid):
    """进程的主窗口在屏幕上的位置 (物理像素)。"""
    user32 = ctypes.windll.user32
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(handle, _):
        # pid 是接口 ping 回来的真实进程号 (虚拟环境的 python.exe 只是启动器, 开窗口的是它的子进程)。
        # 不能按标题找: 用户自己可能也开着一个 GenForm
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(handle, title, 256)
        if owner.value == pid and user32.IsWindowVisible(handle) and title.value.endswith('— GenForm'):
            rect = wintypes.RECT()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            found.append((handle, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
        return True

    user32.EnumWindows(visit, 0)
    return max(found, key=lambda item: item[3] * item[4]) if found else None


def grab(pid, name):
    """把窗口内容存成图片。用 PrintWindow 让窗口把自己画出来: 被别的窗口挡住也能抓到, 也不用把它抢到前台
    (用户可能正开着自己的 GenForm 在用)。抓不到系统给窗口裁的圆角 — 那是合成器做的。"""
    from PySide6.QtGui import QImage
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    handle, _, _, width, height = window_rect(pid)
    time.sleep(0.4)
    user32.GetDC.restype = gdi32.CreateCompatibleDC.restype = gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
    window_dc = user32.GetDC(wintypes.HWND(handle))
    memory_dc = gdi32.CreateCompatibleDC(wintypes.HDC(window_dc))
    bitmap = gdi32.CreateCompatibleBitmap(wintypes.HDC(window_dc), width, height)
    gdi32.SelectObject(wintypes.HDC(memory_dc), wintypes.HANDLE(bitmap))
    user32.PrintWindow(wintypes.HWND(handle), wintypes.HDC(memory_dc), 2)       # 2 = 连显卡画的内容一起
    header = (ctypes.c_uint32 * 10)(40, width, (-height) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(wintypes.HDC(memory_dc), wintypes.HANDLE(bitmap), 0, height, pixels, header, 0)
    gdi32.DeleteObject(wintypes.HANDLE(bitmap))
    gdi32.DeleteDC(wintypes.HDC(memory_dc))
    user32.ReleaseDC(wintypes.HWND(handle), wintypes.HDC(window_dc))
    image = QImage(pixels.raw, width, height, width * 4, QImage.Format_RGB32).copy()
    path = OUT / name
    image.save(str(path))
    print(path, image.width(), image.height(), flush=True)


OUT.mkdir(parents=True, exist_ok=True)
log = open(OUT / 'ui.log', 'w', encoding='utf-8')
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

    time.sleep(1.0)
    PID = call('ping')['pid']
    grab(PID, 'ui_1_empty.png')
    ui('setTab', 'sketch')                              # 翻到草图页: 只是翻页
    ui('useSketchTool', 'rect')                         # 直接点 "矩形": 还没进草图 → 提示选基准面
    time.sleep(0.3)
    grab(PID, 'ui_2_pick_plane.png')
    click(0.5, 0.62)                                    # 在视图里点上视基准面 → 进入草图, 手里就是矩形工具
    time.sleep(0.7)                                     # 等视角转过去
    drag(0.30, 0.30, 0.70, 0.72)                        # 拖出一个矩形
    ui('setSketchTool', 'circle')
    click(0.50, 0.50)
    mouse('move', 0.58, 0.50)
    time.sleep(0.3)
    grab(PID, 'ui_3_sketch_drawing.png')        # 圆还没点第二下: 看得到预览和尺寸
    mouse('press', 0.58, 0.50); mouse('release', 0.58, 0.50)
    ui('setSketchTool', 'select')
    click(0.30, 0.50)                                   # 点矩形左边 → 选中, 右侧出现尺寸
    time.sleep(0.3)
    grab(PID, 'ui_4_sketch_selected.png')
    ui('startCommand', 'extrude')                       # 在草图里直接点 "拉伸凸台": 先存草图, 接着开拉伸面板
    time.sleep(0.9)
    grab(PID, 'ui_4b_extrude_form.png')
    print('模型', json.dumps(call('get_model')['features'], ensure_ascii=False)[:300], flush=True)
    ui('setField', 'distance', 14)
    ui('acceptForm')
    time.sleep(0.8)
    body = call('get_model').get('body', {})
    print('拉伸', bool(body), body.get('size_mm'), flush=True)
    call('fillet', edges='|Z', radius=600)              # 故意失败: 看特征列表怎么显示出错
    ui('startCommand', 'chamfer')
    click(0.5, 0.5)
    time.sleep(0.5)
    grab(PID, 'ui_5_solid.png')
    # 右键手势轮: 建模一套, 草图一套
    def right(kind, x, y):
        ui('_debug_mouse', kind, x, y, 'right')

    ui('cancelForm')
    right('press', 0.5, 0.5)
    right('move', 0.52, 0.5)
    right('move', 0.54, 0.47)                           # 指向右上 (等轴测), 还没划出去
    time.sleep(0.3)
    grab(PID, 'ui_6_gesture_model.png')
    right('move', 0.5, 0.36)                            # 往上划出去 → 上视
    right('release', 0.5, 0.36)
    time.sleep(0.4)
    grab(PID, 'ui_7_after_gesture_top.png')
    ui('editFeature', 'f1')                             # 进草图
    time.sleep(0.7)
    right('press', 0.5, 0.5)
    right('move', 0.47, 0.5)                            # 指向左 (矩形)
    time.sleep(0.3)
    grab(PID, 'ui_8_gesture_sketch.png')
    right('release', 0.47, 0.5)                         # 没划到图标就松手: 指着哪格就执行哪格
    time.sleep(0.3)
    grab(PID, 'ui_9_after_gesture_rect.png')
    ui('cancelSketch')
finally:
    ask({'cmd': 'quit'})
    try:
        process.wait(20)
        print('退出码', process.returncode, flush=True)
    except subprocess.TimeoutExpired:
        print('没有退出', flush=True)
os._exit(0)
