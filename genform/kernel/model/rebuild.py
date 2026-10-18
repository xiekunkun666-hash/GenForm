"""重算: 按特征表一步步算出实体, 记住每一步 (改了后面的特征不用从头算), 存盘的中间结果。"""
from __future__ import annotations

import hashlib
import json
import time
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools

from .base import ANGULAR_DEFLECTION, FeatureError, display_deflection
from .sketches import build_sketch, Context
from .faces import _copy_origins, _inherit_owners
from .solids import apply_blend, combine, _is_empty


# ---------------------------------------------------------------------------
# 重算
# ---------------------------------------------------------------------------
def rebuild(features, upto=None):
    """按顺序重算特征 → (实体或 None, {草图 id: Sketch}, {特征 id: 状态})。"""
    body, ctx, status = _rebuild(features, upto)
    return body, ctx.sketches, status


on_step = None      # 重算每做一个特征之前叫一声: on_step(第几个, 一共几个, 特征名) — 工作进程接上它往界面报进度


_STEPS = []         # 上一次重算每算完一个特征时的样子: [(钥匙, 实体, Context 里各张表的拷贝, 状态)...] — 见 _rebuild


_SPARE = []         # 另一份 _STEPS: 预览算的是 "假如点了确定" 的特征表, 文档自己那份留在这里 (反过来也一样), 来回切不用重算


def _usable(steps, keys, limit):
    """steps 记着的这一串, 能给现在这份特征表 (钥匙 keys) 接上前面多少个特征。"""
    count = 0
    while count < min(limit, len(steps)) and steps[count][0] == keys[count]:
        count += 1
    return 0 if count and steps[count - 1][1] is _MISSING else count    # 只有钥匙、没有样子的一步 (磁盘上读回来的中间步) 接不了


_KEPT = ('sketches', 'curves', 'tools', 'display', 'info', 'helix_axis', 'owners', 'sources', 'origins')


_MISSING = object()         # _STEPS 里只有钥匙、没有当时样子的一步 (从磁盘读回来的只有最后一步的样子)


STORE_AFTER = 2.0           # 一次重算实打实算了这么多秒以上, 就把结果存到磁盘上 (见 store.py): 下次打开不用再等


def _step_keys(features):
    """每个特征一把钥匙: 它自己和排在它前面的所有特征一模一样, 钥匙才一样 (一环扣一环的摘要)。
    基准面、基准轴这些参考几何体是按 id 到整张特征表里查参数的: 排在后面的参考几何体要是被前面的特征提到了
    (它的 id 出现在那个特征的参数里), 从提到它的那个特征起也算进钥匙里。"""
    from .. import features as more
    # 名字、文件夹、加工工艺不算: 改名、归类、绑工艺不改几何, 不该引起重算
    texts = [json.dumps({key: value for key, value in feature.items() if key not in ('name', 'folder', 'process')}, sort_keys=True,
                        ensure_ascii=False, default=str)
             for feature in features]
    borrowed = [[] for _ in features]           # 第 i 个特征起, 要多算进哪些排在后面的参考几何体
    for position, feature in enumerate(features):
        if feature.get('type') in more.REFERENCES:
            mark = json.dumps(feature['id'], ensure_ascii=False)
            first = next((index for index in range(position) if mark in texts[index]), None)
            if first is not None:
                borrowed[first].append(texts[position])
    chain, keys = hashlib.sha1(), []
    for text, extra in zip(texts, borrowed):
        chain.update(text.encode('utf-8'))
        for other in extra:
            chain.update(other.encode('utf-8'))
        keys.append(chain.hexdigest())
    return keys


def _rebuild(features, upto=None):
    """按顺序重算特征 → (实体或 None, Context, {特征 id: 状态})。
    状态: 'ok' / 'suppressed' / 'skipped' (在回滚线之后, 或前面有特征出错) / 'error: 原因'。
    一个特征出错后保留它之前的实体, 后面的特征不再算: 在坏掉的基础上继续算只会给出一串误导的错误。

    接着上一次算: 每算完一个特征就把当时的样子记在 _STEPS 里; 这次的特征表前面一段和上次一模一样的话, 直接从那一段
    的末尾接着算。所以在末尾加一个特征只算这一个 (不是从头把几十个布尔运算再做一遍), 改中间的一个只重算它和它后面的。
    实体本身不会被后面的运算改掉 (每次运算出来的都是新的), 所以记着的可以放心接着用。"""
    from .. import features as more
    body, ctx, status = None, Context(features), {}
    ctx.owners = {}                     # 当前实体的面序号 → 做出这张面的特征 (可直接序列化)
    failed = False
    keys = _step_keys(features)
    limit = len(features) if upto is None else max(0, min(int(upto), len(features)))
    start, other = _usable(_STEPS, keys, limit), _usable(_SPARE, keys, limit)
    if other > start:                                   # 另一份记着的接得更长 (预览完了回到文档, 或者预览的被确定了): 换过来用
        _STEPS[:], _SPARE[:] = list(_SPARE), list(_STEPS)
        start = other
    elif start < len(_STEPS):                           # 这一份后面的要扔了: 先留个底, 说不定马上又要回到它
        _SPARE[:] = _STEPS
    del _STEPS[start:]
    if start == 0 and limit > 0:
        start = _restore(features, keys, limit)         # 磁盘上有这份特征表算到头的样子: 直接用
    if start:
        _, body, tables, kept = _STEPS[start - 1]
        for name in _KEPT:
            setattr(ctx, name, dict(tables.get(name) or {}))
        status = dict(kept)
    began = time.perf_counter()
    for index, feature in enumerate(features):
        if index < start:
            continue
        step_began = time.perf_counter()
        before = body
        identifier = feature['id']
        if failed or (upto is not None and index >= upto):
            status[identifier] = 'skipped'
            continue
        if feature.get('suppressed'):
            status[identifier] = 'suppressed'
            _STEPS.append((keys[index], body, {name: dict(getattr(ctx, name)) for name in _KEPT}, dict(status)))
            continue
        if on_step is not None and feature.get('type') != 'sketch':        # 草图一闪就过, 不值得报
            on_step(index, len(features), feature.get('name') or identifier)
        kind, params = feature.get('type'), feature.get('params') or {}
        ctx.current = identifier
        try:
            if kind == 'sketch':
                ctx.sketches[identifier] = build_sketch(params, features)
            elif kind == 'extrude' or kind in more.MAKERS:
                solid = ctx.make(kind, params, body)
                operation = params.get('op', more.DEFAULT_OP.get(kind, 'add'))
                if operation == 'pocket' and params.get('wall'):
                    operation = f'pocket:{float(params["wall"]):g}'     # 壁厚跟着方式走: 镜像、阵列复制的凹槽也一样厚
                body = combine(body, solid, operation)
                ctx.tools[identifier] = (solid, operation)
            elif kind == 'fillet':
                body = apply_blend(body, params, True)
            elif kind == 'chamfer':
                body = apply_blend(body, params, False)
            elif kind in more.MODIFIERS:
                ctx.copied = ctx.copied_origins = None
                body = more.MODIFIERS[kind](body, params, ctx)
                if ctx.copied:                  # 阵列 / 镜像: 复制出来的这些记成它的工具体, 它自己也能再被阵列、镜像
                    ctx.tools[identifier] = list(ctx.copied)
                    ctx.sources[identifier] = list(ctx.copied_origins or ())
            elif kind in more.CURVES:
                ctx.curves[identifier] = more.CURVES[kind](body, params, ctx, identifier)
                ctx.display.setdefault(identifier, ctx.curves[identifier])
            elif kind in more.REFERENCES:
                ctx.display[identifier] = more.reference(kind, body, params, ctx, identifier)
            else:
                raise FeatureError(f'不认识的特征类型 {kind!r}')
            status[identifier] = 'ok'
            if body is not before and not _is_empty(body):
                # 归属和 "从哪个特征复制来的" 一起继承: 值是 (特征, 原件)
                paired = {index: (owner, ctx.origins.get(index)) for index, owner in ctx.owners.items()}
                paired = _inherit_owners(before, body, paired, (identifier, None), ctx.seen_faces)
                if kind in more.MODIFIERS and ctx.copied:
                    _copy_origins(body, paired, (identifier, None), ctx.copied, ctx.sources[identifier], ctx.seen_faces)
                ctx.owners = {index: owner for index, (owner, _) in paired.items()}
                ctx.origins = {index: origin for index, (_, origin) in paired.items() if origin}
            _STEPS.append((keys[index], body, {name: dict(getattr(ctx, name)) for name in _KEPT}, dict(status)))
            _COST[keys[index]] = time.perf_counter() - step_began
        except FeatureError as error:
            status[identifier] = f'error: {error}'
            failed = True
        except Exception as error:          # 内核自己抛的异常: 也只让这一个特征失败
            status[identifier] = f'error: 内核错误 {type(error).__name__}: {error}'
            failed = True
    if not failed and start < limit and time.perf_counter() - began >= STORE_AFTER:
        keep()                              # 这次算了好一会儿: 存到磁盘上, 下次打开直接读
    return body, ctx, status


def keep():
    """把刚算完的这份 (最后一步的样子) 存到磁盘上。"""
    from .. import store
    if store.folder() is None:              # 磁盘缓存关着: 什么都不做 (原来照样先网格化一遍, 白花十几秒)
        return
    if _STEPS and _STEPS[-1][1] is not _MISSING and not _is_empty(_STEPS[-1][1]):
        key, body, tables, status = _STEPS[-1]
        # 草图不存 (读回来时照参数重画一遍很快, 而它里面的东西又多又碎); 面先网格化好, 连网格一起存。
        # 先扔掉布尔运算留下的旧网格 (见 display._drop_stale_meshes): 带着它网格化, 911 的车身要十几秒, 扔了只要零点几秒
        if not meshed(body):
            BRepTools.Clean_s(body)
            BRepMesh_IncrementalMesh(body, display_deflection(body), False, ANGULAR_DEFLECTION, True)     # 和显示时同一个精度
            _MESHED[:] = [body]
        store.save(key, body, {name: value for name, value in tables.items() if name != 'sketches'}, status)
        _keep_checkpoints(store)


CHECKPOINT_EVERY = 45.0     # 秒: 中间每算了这么久存一个检查点
_COST = {}                  # 钥匙 → 这一步实打实算了几秒 (本进程里算过的)


def _keep_checkpoints(store):
    """除了最后一步, 中间每累计算了 CHECKPOINT_EVERY 秒存一个检查点 (已经在盘上的不重存)。打开一个三百个特征的零件、
    改中间的某一个时, 从它前面最近的检查点接着算, 不用从第一个特征算起 (911 整车从头算要七分多钟)。"""
    spent = 0.0
    for key, body, tables, status in _STEPS[:-1]:
        spent += _COST.get(key, 0.0)
        if spent < CHECKPOINT_EVERY or body is _MISSING or tables is None or _is_empty(body):
            continue
        spent = 0.0
        if not store.has(key):
            store.save(key, body, {name: value for name, value in tables.items() if name != 'sketches'}, status)
    if len(_COST) > 5000:
        _COST.clear()


_MESHED = []        # 网格是刚刚干干净净做好的那个实体 (从磁盘缓存读回来的 / keep 刚网格化的): 显示时不用再扔掉重做


def meshed(body):
    return any(body is item for item in _MESHED)


def _restore(features, keys, limit):
    """磁盘上这份特征表能接上的最靠后的一份 (算到头的, 没有就找中间的检查点) → 摆进 _STEPS, 返回它是第几个特征之后;
    一份都没有: 0。改了中间的特征再打开, 从它前面最近的检查点接着算。"""
    from .. import store
    for count in range(limit, 0, -1):
        if not store.has(keys[count - 1]):
            continue
        found = store.load(keys[count - 1])
        if found is None:
            continue
        body, tables, status = found
        try:
            tables['sketches'] = {feature['id']: build_sketch(feature.get('params') or {}, features) for feature in features[:count]
                                  if feature.get('type') == 'sketch' and status.get(feature['id']) == 'ok'}
        except Exception:
            return 0
        _STEPS[:] = [(key, _MISSING, None, None) for key in keys[:count - 1]] + [(keys[count - 1], body, tables, status)]
        _MESHED[:] = [body]
        return count
    return 0
