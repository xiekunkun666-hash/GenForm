"""装配体的单选和框选；_picked 保留为属性面板使用的主选。"""
from __future__ import annotations

from PySide6.QtCore import Slot


class PartSelectionMixin:
    def _selected_part_indices(self):
        signature = tuple(id(part) for part in self._parts)
        if (getattr(self, '_part_selection_primary', None) != self._picked
                or getattr(self, '_part_selection_signature', None) != signature):
            return {self._picked} if 0 <= self._picked < len(self._parts) else set()
        return set(self._part_selection)

    def _set_part_selection(self, indices, additive, visible_only):
        selected = self._selected_part_indices() if additive else set()
        candidates = []
        for index in indices:
            if isinstance(index, int) and 0 <= index < len(self._parts) and index not in candidates:
                candidates.append(index)
        selected.update(candidates)
        if visible_only:
            allowed = {index for index in range(len(self._parts)) if index not in self._hidden_parts
                       and (self._alone_part is None or index == self._alone_part)}
            selected.intersection_update(allowed)
            candidates = [index for index in candidates if index in allowed]
        primary = candidates[-1] if candidates else self._picked if self._picked in selected else max(selected, default=-1)
        before = self._selected_part_indices(), self._picked
        self._part_selection = selected
        self._picked = self._part_selection_primary = primary
        self._part_selection_signature = tuple(id(part) for part in self._parts)
        if selected:
            self._joint_picked = -1
        if before != (selected, primary):
            self._push_parts()
            self.changed.emit()

    @Slot(int)
    @Slot(int, bool)
    def selectPart(self, index, additive=False):
        """单击替换选择，Ctrl 单击累加；树上仍可选隐藏件以编辑属性。"""
        if 0 <= index < len(self._parts) and 0 <= self._joint_adding < len(self._joints):
            self._toggle_joint_part(index)
            return
        self._set_part_selection([index], additive, visible_only=False)

    @Slot('QVariantList', bool)
    def selectParts(self, indices, additive=False):
        """框选只接受当前可见的组件；空框清空，Ctrl 空框保留选择。"""
        self._set_part_selection(indices, additive, visible_only=True)
