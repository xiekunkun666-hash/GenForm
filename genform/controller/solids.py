"""零件里的实体块和面: 认面、隐藏 / 显示、孤立时要用的面集合。"""
from __future__ import annotations

from .. import features as table
from .common import SHOW_OF, solid_blocks


class SolidMixin:
    """零件里的实体块和面 (控制器的一部分)。"""

    # ---- 点特征 / 草图弹出来的小工具条 ----
    def _find(self, identifier):
        return next((feature for feature in self.session.document.features if feature['id'] == identifier), None)

    def _is_line_feature(self, feature):
        """画出来是线的特征 (草图、曲线、参考几何体): 可以单独隐藏。别的特征都长在同一个实体上。"""
        return feature['type'] == 'sketch' or feature['type'] in SHOW_OF or feature['type'] in table.CURVE_KINDS

    def _is_hidden(self, feature):
        if self._is_line_feature(feature):
            return feature['id'] in self._hidden_ids
        hidden = self._hidden_faces()
        return any(face['id'] in hidden for face in self.session.model.get('faces', ()) if face.get('feature') == feature['id'])

    # ---- 实体块: 零件里互不相连的几块实体 (导入的装配体、几次拉伸没连上的) 可以一块一块地隐藏 ----
    @staticmethod
    def _face_key(face):
        return (face.get('type'), tuple(round(float(value), 3) for value in face.get('center', ())), round(float(face.get('area', 0.0)), 3))

    def _solids(self):
        """→ (每张面属于第几块, 每块的面 id 列表); 模型没换就用上次算的。"""
        model = self.session.model
        if self._solid_cache is None or self._solid_cache[0] is not model:
            self._solid_cache = (model, solid_blocks(model.get('faces') or []))
        return self._solid_cache[1]

    def _hidden_faces(self):
        """被隐藏的面 (编号)。改了模型以后, 类型、形心、面积都没变的面还认得出来, 照样隐藏着。"""
        if not self._hidden_keys or not self.session.model.get('has_body'):
            return set()
        return {face['id'] for face in self.session.model.get('faces') or () if self._face_key(face) in self._hidden_keys}

    def _set_faces_hidden(self, face_ids, hide):
        faces = self.session.model.get('faces') or []
        keys = {self._face_key(faces[index]) for index in face_ids if 0 <= index < len(faces)}
        if hide:
            self._hidden_keys |= keys
        else:
            # 顺手丢掉模型改过以后已经认不出来的旧记录
            self._hidden_keys = {self._face_key(faces[index]) for index in self._hidden_faces()} - keys

    def _part_faces(self, face_id):
        """视图里点中这张面时 "隐藏" 藏哪些面: 做出它的那个特征做出来的那部分 (点机翼就只藏机翼);
        不知道是哪个特征做的 (导入的) 就是它所在的那一整块实体。"""
        faces = self.session.model.get('faces') or []
        if not 0 <= face_id < len(faces):
            return []
        feature = faces[face_id].get('feature')
        if feature is None:
            return self._solid_faces([face_id])
        return [face['id'] for face in faces if face.get('feature') == feature]

    def _solid_faces(self, face_ids):
        """这些面所在的那几整块相连的实体上的全部面。"""
        owner, blocks = self._solids()
        return [index for block in sorted({owner[index] for index in face_ids if 0 <= index < len(owner)}) for index in blocks[block]]

    def _scene_faces(self, scene):
        """视图里点中的面 (点的是边: 边两侧的面)。"""
        if scene['kind'] == 'face':
            return [scene['id']]
        return [face['id'] for face in self.session.model.get('faces', ()) if scene['id'] in face.get('edges', ())]

    def _source_sketch(self, feature):
        """这个特征用的草图 (没有就是 None)。"""
        source = self._find(feature['params'].get('sketch')) if feature['type'] != 'sketch' else None
        return source if source is not None and source['type'] == 'sketch' else None
