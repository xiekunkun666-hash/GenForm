# -*- coding: utf-8 -*-
"""重算结果磁盘缓存的印记: 算几何的源码 (含拆出去的子包) 哪个变了, 旧缓存都要作废。"""
import unittest

from genform.kernel import store


class Stamp(unittest.TestCase):
    def test_stamp_covers_split_packages(self):
        names = {name for name, _ in store._source_files()}
        for wanted in ('model/rebuild.py', 'model/solids.py', 'ops/modify.py', 'occ_compat.py',
                       '../sketchgeo/base.py', '../features.py', '../planes.py'):
            self.assertIn(wanted, names)
        self.assertFalse(any('__pycache__' in name for name in names))


if __name__ == '__main__':
    unittest.main()
