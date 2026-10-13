"""Read runtime monitor metadata, falling back to bundled static evidence."""
import json
import os
from pathlib import Path

STATIC = Path(__file__).resolve().parent / 'rules/sources'


def status():
    configured = os.getenv('RULE_SOURCE_DIR')
    root = Path(configured) if configured else STATIC
    def read(name, default):
        path = root / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
    manifest = read('manifest.json', {'sources': []})
    pending = read('pending_review.json', {'updates': []})
    return {'mode': 'runtime_monitor' if configured else 'bundled_static', 'checked_at': manifest.get('checked_at'),
            'automatic_activation': False, 'sources': manifest['sources'],
            'pending_updates': [u for u in pending['updates'] if u['status'] == 'PENDING_REVIEW'],
            'notice': '来源内容变化不等于法规修订；待复核记录不会自动替换运行规则。'}
