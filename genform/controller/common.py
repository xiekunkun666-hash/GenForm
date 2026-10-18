"""控制器共用的表 (工具提示、显示样式、视角…) 和小工具 (实体分块、视图适配)。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl

from ..document import DocumentError
from ..view.viewer.screenshot import ScreenshotRequest


STATUS_TEXT = {'ok': '', 'suppressed': '已抑制', 'skipped': '未计算', 'pending': '计算中'}


TOOL_HINTS = {
    'select': '点选图形（Ctrl 加选，空白处拖出方框框选）；拖动移动；拖控制点改形状；双击选一整串；Delete 删除',
    'line': '连续点出直线，点回起点闭合；回车、双击或 Esc 结束这一串',
    'centerline': '中心线：和直线一样画，画出来的是构造线（虚线）——只作参考和旋转轴，不参与拉伸',
    'midline': '中点线：点中点，再点一端（另一端对称着出来）',
    'rect': '点两个对角，或按住拖出矩形',
    'crect': '中心矩形：点中心，再点一个角',
    'rect3': '3 点边角矩形：点一条边的两端，再拉出另一边的长度',
    'crect3': '3 点中心矩形：点中心 → 点一条边的中点 → 拉出这条边的半长',
    'pgram': '平行四边形：依次点三个角，第四个角自动补上',
    'circle3': '周边圆：点圆周上的三个点',
    'cslot': '中心点直槽口：点槽的中心 → 点一头的圆心 → 拉出槽宽再点',
    'aslot3': '三点圆弧槽口：点中心线圆弧的起点 → 终点 → 弧上一点 → 拉出槽宽再点',
    'caslot': '中心点圆弧槽口：点圆心 → 点起点 → 顺着要画的方向转到终点再点 → 拉出槽宽再点',
    'sspline': '样式样条曲线：依次点控制点（曲线被它们拉过去，不经过中间的点），回车或双击结束；最多 12 个',
    'equation': '方程式驱动的曲线：点一下放置，再在左上角的面板里改式子和范围',
    'dimension': '智能尺寸：点一个图形改它的尺寸；再点另一处（端点、圆心或线）拉出距离标注，点一下放下',
    'extend': '延伸实体：点直线或圆弧要延长的那一头，延到碰上别的线为止',
    'circle': '点圆心，再点圆周上一点',
    'arc': '圆心/起/终点画弧：点圆心 → 点起点 → 顺着要画的方向转到终点再点',
    'slot': '直槽口：点第一个圆心 → 点第二个圆心 → 拉出槽宽再点',
    'ngon': '多边形：点中心，再点一个顶点（边数在左上角的面板里改）',
    'ellipse': '椭圆：点中心 → 点长轴端点 → 拉出短轴再点',
    'spline': '样条曲线：依次点经过的点，回车或双击结束，点回起点闭合',
    'point': '点：单击放置一个点（可以被别的图形捕捉）',
    'text': '文本：单击放置，再在左上角的面板里改文字和字高（先选中一条曲线再点“文本”= 沿这条曲线排）',
    'fillet': '绘制圆角：点两条直线相交的尖角（半径在左上角的面板里改）',
    'trim': '剪裁实体：点要剪掉的那一段，剪到它和别的线相交的地方',
    'offset': '等距实体：点一个图形，再往要偏的那一侧移动，到合适的距离再点',
    'mirror': '镜向实体：点两个点定出镜向轴（原来的图形保留）',
    'move': '移动实体：点起点，再点终点',
    'convert': '转换实体引用：点实体的边（蓝色的线），把它拷进草图',
}


OPERATION_HINTS = {'pattern': '线性草图阵列：在左上角的面板里填数量和间距，确定', 'repair': '修复草图：问题在视图里用点标出来了',
                   'cpattern': '圆周草图阵列：在左上角的面板里填数量、总角度和中心，确定',
                   'relation': '添加几何关系：在左上角的面板里选一种关系，点“添加”',
                   'dimension': '智能尺寸：在属性管理器里改数字；再点另一处（端点、圆心或线）拉出距离标注'}


# 视图上方那排按钮用的几张表
DISPLAY_STYLES = [('shaded_edges', '带边线上色'), ('shaded', '上色'), ('hlr', '消除隐藏线'), ('hlv', '隐藏线可见'), ('wire', '线架图')]


SCENE_NAMES = [('auto', '跟随界面主题'), ('fade', '三点渐褪'), ('white', '单白色'), ('gray', '带顶光源的灰色'), ('spot', '柔光聚光灯')]


ORIENTATIONS = [('front', '前视'), ('back', '后视'), ('left', '左视'), ('right', '右视'), ('top', '上视'), ('bottom', '下视'),
                ('iso', '等轴测'), ('normal', '正视于')]


SHOW_ITEMS = [('main_planes', '主要基准面'), ('planes', '基准面'), ('axes', '基准轴'), ('csys', '坐标系'), ('points', '点'),
              ('origin', '原点'), ('curves', '曲线'), ('sketches', '草图'), ('sketch3d', '3D 草图'), ('com', '质心'), ('bbox', '边界框')]


SHOW_OF = {'plane': 'planes', 'axis': 'axes', 'csys': 'csys', 'point': 'points', 'com': 'com', 'bbox': 'bbox',
           'sketch': 'sketches', 'sketch3d': 'sketch3d'}       # 特征类型 → 归哪一项管 (其余的曲线特征都归 curves)


MEASURE_NAMES = {'plane': '平面', 'cylinder': '圆柱面', 'cone': '圆锥面', 'sphere': '球面', 'torus': '圆环面', 'surface': '曲面',
                 'line': '直边', 'circle': '圆弧边', 'curve': '曲线边', 'vertex': '顶点'}


PREVIEW_TINT = (1.0, 0.84, 0.22)        # 预览出来的实体: 黄色, 和已经定下来的灰色分得开


HOLE_KINDS = ('hole', 'hole_adv', 'stud', 'screw')       # 位置由一个草图定的孔 / 螺柱: 有 "编辑孔草图"


RESERVED_KEYS = ('esc', 'escape', 'return', 'enter')    # 取消和确认: 不让改派给别的功能


DRAW_TOOLS = ('line', 'centerline', 'midline', 'rect', 'crect', 'rect3', 'crect3', 'pgram', 'circle', 'circle3', 'arc', 'slot',
              'cslot', 'aslot3', 'caslot', 'ngon', 'ellipse', 'spline', 'sspline', 'equation', 'point', 'text')


def _local(path):
    """QML 文件对话框给的是 file:/// 地址。"""
    text = str(path)
    return QUrl(text).toLocalFile() if text.startswith('file:') else text


def solid_blocks(faces):
    """零件里互不相连的几块实体 → (每张面属于第几块, 每块的面 id 列表)。共用一条边的两张面在同一块上,
    不同的实体块之间不共用边。faces 是模型里的面信息 (id 就是它在表里的位置, 'edges' 是围着它的边)。"""
    parent = list(range(len(faces)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index
    if not any(face.get('edges') for face in faces):
        parent = [0] * len(faces)                   # 没有边的信息: 当成一整块
    first = {}
    for face in faces:
        for edge in face.get('edges', ()):
            a, b = root(first.setdefault(edge, face['id'])), root(face['id'])
            if a != b:
                parent[a] = b
    number = {}
    owner = [number.setdefault(root(index), len(number)) for index in range(len(faces))]
    blocks = [[] for _ in number]
    for index, block in enumerate(owner):
        blocks[block].append(index)
    return owner, blocks


class _ViewAdapter:
    """会话的视图命令 (set_view / screenshot) 落到三维视图控件上。"""

    SCREENSHOT_TIMEOUT_MS = 15000

    def __init__(self, controller):
        self._controller = controller
        self._shot_state = None

    def set_view(self, name):
        viewport = self._controller.viewport
        if viewport is None:
            raise DocumentError('三维视图还没准备好')
        viewport.setView(name)
        return {'view': name}

    def screenshot(self, path, view):
        viewport = self._controller.viewport
        if viewport is None or not viewport.screenshot_ready():
            raise DocumentError('三维视图还没准备好')
        if self._shot_state is not None:
            raise DocumentError('已有截图正在保存')

        def later(reply):
            if self._shot_state is not None:
                reply({'ok': False, 'error': '已有截图正在保存'})
                return
            request = None
            try:
                request = ScreenshotRequest(path)
                timer = QTimer(request)
                timer.setSingleShot(True)
                timer.setTimerType(Qt.PreciseTimer)
            except Exception as error:
                if request is not None:
                    request.deleteLater()
                reply({'ok': False, 'error': f'截图失败: {type(error).__name__}: {error}'})
                return
            self._shot_state = request
            done, connected = False, False

            def finish(result):
                nonlocal done
                if done:
                    return
                done = True
                request.cancel()
                timer.stop()
                if self._shot_state is request:
                    self._shot_state = None
                try:
                    request.finished.disconnect(saved)
                    if connected:
                        viewport.destroyed.disconnect(destroyed)
                except (RuntimeError, TypeError):
                    pass
                try:
                    viewport.cancel_shot(request)
                except (RuntimeError, TypeError):
                    pass
                try:
                    viewport.release_hover()        # 截完了: 悬停照常
                except (RuntimeError, TypeError, AttributeError):
                    pass
                request.deleteLater()
                reply(result)

            def saved(result):
                finish({'ok': True, 'path': result} if result else
                       {'ok': False, 'error': request.error or '截图保存失败'})

            def timed_out():
                finish({'ok': False, 'error': f'截图超时（{self.SCREENSHOT_TIMEOUT_MS / 1000:g}秒）'})

            def destroyed(*args):
                finish({'ok': False, 'error': '三维视图已销毁，截图取消'})

            try:
                request.finished.connect(saved)
                timer.timeout.connect(timed_out)
                viewport.destroyed.connect(destroyed)
                connected = True
                request.start_timeout(self.SCREENSHOT_TIMEOUT_MS)
                timer.start(self.SCREENSHOT_TIMEOUT_MS)
                if self._controller.viewport is not viewport or not viewport.screenshot_ready():
                    raise DocumentError('三维视图还没准备好')
                if view:
                    viewport.snap_view(view)
                viewport.clear_hover(hold=True)
                viewport.request_shot(path, request=request)
            except Exception as error:
                finish({'ok': False, 'error': f'截图失败: {type(error).__name__}: {error}'})
        return later
