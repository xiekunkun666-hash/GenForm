"""Run GenForm's native design checks without changing engineering rules."""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main(folder):
    folder = folder.resolve()
    with tempfile.TemporaryDirectory(prefix='skye2-native-check-') as temporary:
        os.environ['GENFORM_SETTINGS'] = str(Path(temporary) / 'settings.json')
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtGui import QGuiApplication
        from genform.app import AppController
        from genform.document import Document
        from genform.kernel import build
        from genform.kernel import inspect as inspection
        from genform.kernel.model import rebuild as rebuilding
        from genform import checks, rules
        from genform.session import Session

        application = QGuiApplication.instance() or QGuiApplication([])
        controller = AppController(Session())
        controller._set_kind('assembly')
        controller.sim.pin()
        controller.sim.openAssembly(str(folder / 'SKYE2_复现装配.gasm'))
        controller.sim._live_timer.stop()
        controller.sim._live['running'] = False
        outputs = []
        rebuilding.on_step = lambda index, total, name, *rest: print(f'{index}/{total} {name}', flush=True)
        controller.sim.check(outputs.append)
        controller.sim._live_timer.stop()
        if len(outputs) != 1:
            raise RuntimeError('Native assembly design check did not finish')
        issues = outputs[0]
        report = {'scope': 'GenForm native assembly check; original/default design rules unchanged',
                  'rules': rules.effective(), 'issues': issues,
                  'counts': dict(collections.Counter(issue['level'] for issue in issues)),
                  'contacts': controller.sim._live['result'], 'live_error': controller.sim._live['error']}
        save(folder / 'design_check_assembly.json', report)
        print('ASSEMBLY', json.dumps(report['counts']), flush=True)
        for issue in issues:
            print(issue['level'], issue['code'], issue['title'], issue.get('detail', ''), flush=True)
        assembly = json.loads((folder / 'SKYE2_复现装配.gasm').read_text(encoding='utf-8'))
        parts = []
        for row in assembly['parts']:
            document = Document()
            document.open(str(folder / row['file']))
            model = build.build_model(document.features, document.upto)
            geometry = inspection.inspect(document.features, document.upto, {'rules': rules.effective()})
            found = checks.run(document.features, model, geometry, rules.effective(), document.props.get('material', ''))
            result = {'name': row['name'], 'file': row['file'], 'valid': geometry.get('valid'),
                      'feature_statuses': model.get('status'), 'issues': found,
                      'counts': dict(collections.Counter(issue['level'] for issue in found))}
            save(folder / f'design_check_{Path(row["file"]).stem}.json', result)
            parts.append(result)
            print('PART', row['file'], json.dumps(result['counts']), flush=True)
        save(folder / 'design_check_summary.json', {'assembly': report['counts'],
                                                   'parts': [{'name': part['name'], 'counts': part['counts']} for part in parts],
                                                   'identical_to_manufacturer': False,
                                                   'reason': 'Public reference lacks hole depths, several locations, internal channels and connector tolerances'})
        controller.session.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder', type=Path)
    arguments = parser.parse_args()
    main(arguments.folder)
